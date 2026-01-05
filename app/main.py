import asyncio
import logging
import secrets
import time
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from starlette.middleware.base import BaseHTTPMiddleware
from app.utils import get_cache_dir, load_json_file
from app.models import (
    ArticlesByUrlRequest,
    LoginRequest,
    ChangePasswordRequest,
    NotificationConfigRequest,
)
from app.wechat import get_wechat_client
from app.auth import (
    verify_user,
    change_password,
    init_users,
    load_notification_config,
    save_notification_config,
)
from app.notification import NotificationSender
from app.utils import log

scheduler = AsyncIOScheduler()
request_semaphore = asyncio.Semaphore(5)
last_notification_time: int = 0

class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        async with request_semaphore:
            response = await call_next(request)
            return response

class PersistentSessionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, session_dir: str = "./cache/sessions"):
        super().__init__(app)
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_file(self, session_id: str) -> Path:
        return self.session_dir / f"{session_id}.json"

    def _load_session(self, session_id: str) -> dict:
        session_file = self._get_session_file(session_id)
        if not session_file.exists():
            return {}

        try:
            data = json.loads(session_file.read_text())
            if data.get("expire_at", 0) < time.time():
                session_file.unlink()
                return {}
            return data.get("data", {})
        except (json.JSONDecodeError, KeyError):
            return {}

    def _save_session(self, session_id: str, session_data: dict) -> None:
        session_file = self._get_session_file(session_id)
        data = {
            "data": session_data,
            "expire_at": time.time() + 7 * 24 * 3600,
        }
        session_file.write_text(json.dumps(data))

    async def dispatch(self, request: Request, call_next):
        session_id = request.cookies.get("session_id")
        if not session_id:
            session_id = secrets.token_urlsafe(32)

        session_data = self._load_session(session_id)
        request.state.session = session_data

        response = await call_next(request)

        if hasattr(request.state, "session"):
            self._save_session(session_id, request.state.session)

        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="lax",
        )

        return response

async def send_offline_notification():
    try:
        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"【公众号离线通知】\n公众号已离线，请及时登录。\n检测时间：{current_time_str}"

        notification_config_file = get_cache_dir() / "notification_config.json"
        all_configs = load_json_file(notification_config_file, default=None)

        if not all_configs:
            log("[离线通知] 未找到通知配置文件，跳过通知")
            return

        for username, config in all_configs.items():
            selected_type = config.get("selected_type")
            if not selected_type:
                log(f"[离线通知] 用户 {username} 未配置通知类型，跳过")
                continue

            robot_config = config.get(selected_type, {})
            webhook_url = robot_config.get("webhook_url", "")
            secret = robot_config.get("secret", "")

            if not webhook_url:
                log(f"[离线通知] 用户 {username} 未配置 {selected_type} Webhook，跳过")
                continue

            log(f"[离线通知] 向用户 {username} 发送 {selected_type} 通知...")
            success, msg = await NotificationSender.send_notification(
                selected_type, webhook_url, secret, message
            )

            if success:
                log(f"[离线通知] 用户 {username} 通知发送成功")
            else:
                log(f"[离线通知] 用户 {username} 通知发送失败: {msg}")

    except Exception as e:
        log(f"[离线通知] 发送通知异常: {e}")

async def check_online_task():
    global last_notification_time

    client = get_wechat_client()
    if client.token:
        try:
            result = await client.is_online()
            if result["online"]:
                log("[在线检查] 会话正常")
            else:
                log(f"[在线检查] 会话已离线: {result['message']}")
                if not client.logout_time:
                    client.logout_time = int(time.time())
                    log("[在线检查] 已记录退出时间")

                current_time = int(time.time())
                time_since_last = current_time - last_notification_time

                if time_since_last >= 60 * 10:
                    await send_offline_notification()
                    last_notification_time = current_time
                    log("[在线检查] 已发送离线通知")
                else:
                    remaining = 600 - time_since_last
                    log(f"[在线检查] 距离上次通知不足10分钟，跳过通知（还需等待 {remaining} 秒）")
        except Exception as e:
            log(f"[在线检查] 检查异常: {e}")
    else:
        log("[在线检查] 未登录，跳过")

async def keep_alive_task():
    client = get_wechat_client()
    if client.token:
        try:
            success = await client.keep_alive()
            if success:
                log("[保活任务] 会话保活成功")
            else:
                log("[保活任务] 会话保活失败，可能需要重新登录")
        except Exception as e:
            log(f"[保活任务] 保活异常: {e}")
    else:
        log("[保活任务] 未登录，跳过")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_users()
    log("[启动] 用户数据已初始化")

    scheduler.add_job(check_online_task, "interval", minutes=1, id="check_online")
    scheduler.add_job(keep_alive_task, "interval", minutes=30, id="keep_alive")
    scheduler.start()
    log("[启动] 后台任务已启动 - 在线检查(每分钟) + 保活(每30分钟)")

    yield

    scheduler.shutdown()
    client = get_wechat_client()
    await client.close()
    log("[关闭] 服务已停止")


app = FastAPI(
    title="微信公众号文章爬虫",
    description="获取微信公众号文章列表的API服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(PersistentSessionMiddleware)
app.add_middleware(ConcurrencyLimitMiddleware)

@app.post("/articles-by-url")
async def get_articles_by_url(request: ArticlesByUrlRequest) -> dict[str, Any]:
    if (os.getenv("API_TOKEN") != "" and os.getenv("API_TOKEN") is not None) and os.getenv("API_TOKEN") != request.api_token:
        return {
            "success": False,
            "message": "密钥不正确",
        }

    client = get_wechat_client()
    if not client.token:
        return {
            "success": False,
            "message": "未登录，请先扫码登录",
        }
    
    try:
        biz = await client.extract_biz_from_url(request.url)
        
        if not biz:
            return {
                "success": False,
                "message": "无法从该链接中提取biz值",
                "url": request.url,
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"提取biz值失败: {str(e)}",
            "url": request.url,
        }
    
    MAX_PER_PAGE = 20
    total_needed = request.number
    all_articles: list = []
    begin = 0
    total_count = 0
    
    try:
        while len(all_articles) < total_needed:
            result = await client.get_articles(
                fakeid=biz,
                begin=begin,
                count=MAX_PER_PAGE,
            )
            
            if begin == 0:
                total_count = result.get("total_count", 0)
            
            publish_list = result.get("publish_list", [])
            
            if not publish_list:
                break
            
            for publish_item in publish_list:
                publish_info = publish_item.get("publish_info", {})
                appmsgex_list = publish_info.get("appmsgex", [])
                
                for article in appmsgex_list:
                    simplified_article = {
                        "msgid": article.get("appmsgid"),
                        "aid": article.get("aid"),
                        "link": article.get("link"),
                        "title": article.get("title"),
                        "cover": article.get("cover"),
                        "digest": article.get("digest"),
                        "create_time": article.get("create_time"),
                        "update_time": article.get("update_time"),
                    }
                    all_articles.append(simplified_article)
                    
                    if len(all_articles) >= total_needed:
                        break
                
                if len(all_articles) >= total_needed:
                    break
            
            begin += len(publish_list)
            if begin >= total_count:
                break
        
        return {
            "success": True,
            "biz": biz,
            "data": {
                "total_count": total_count,
                "article_count": len(all_articles),
                "articles": all_articles,
            }
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"获取文章列表失败: {str(e)}",
            "biz": biz,
        }

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def admin_login(request: Request, login_data: LoginRequest):
    username = login_data.username
    password = login_data.password

    if verify_user(username, password):
        request.state.session["user"] = username
        request.state.session["logged_in"] = True
        return JSONResponse(
            content={
                "success": True,
                "message": "登录成功",
            }
        )
    else:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "用户名或密码错误",
            }
        )

@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/change-password", response_class=HTMLResponse)
async def admin_change_password_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("change_password.html", {"request": request})

@app.post("/change-password")
async def admin_change_password(request: Request, password_data: ChangePasswordRequest):
    if not request.state.session.get("logged_in"):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "未登录，请先登录",
            }
        )

    username = request.state.session.get("user")
    old_password = password_data.old_password
    new_password = password_data.new_password

    success, message = change_password(username, old_password, new_password)
    if success:
        return JSONResponse(
            content={
                "success": True,
                "message": message,
            }
        )
    else:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": message,
            }
        )

@app.get("/notification-config")
async def admin_notification_config_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=302)

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header:
        username = request.state.session.get("user")
        config = load_notification_config(username)

        return JSONResponse(
            content={
                "success": True,
                "config": config,
            }
        )
    return templates.TemplateResponse("notification_config.html", {"request": request})


@app.post("/notification-config")
async def save_notification_config_route(request: Request, config_data: NotificationConfigRequest):
    if not request.state.session.get("logged_in"):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "未登录，请先登录",
            }
        )

    username = request.state.session.get("user")

    config = {
        "selected_type": config_data.selected_type,
        "dingtalk": {
            "webhook_url": config_data.dingtalk.webhook_url,
            "secret": config_data.dingtalk.secret,
        },
        "wecom": {
            "webhook_url": config_data.wecom.webhook_url,
            "secret": config_data.wecom.secret,
        },
        "feishu": {
            "webhook_url": config_data.feishu.webhook_url,
            "secret": config_data.feishu.secret,
        },
    }
    save_notification_config(username, config)

    return JSONResponse(
        content={
            "success": True,
            "message": "通知配置已保存",
        }
    )


@app.get("/wechat-login", response_class=HTMLResponse)
async def admin_wechat_login_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("wechat_login.html", {"request": request})


@app.get("/wechat-qrcode")
async def admin_wechat_qrcode(request: Request):
    if not request.state.session.get("logged_in"):
        raise HTTPException(status_code=401, detail="未登录后台")

    client = get_wechat_client()

    try:
        qrcode_bytes = await client.init_login()

        return Response(
            content=qrcode_bytes,
            media_type="image/png",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取二维码失败: {str(e)}")


@app.post("/wechat-status")
async def admin_wechat_status(request: Request):
    if not request.state.session.get("logged_in"):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "未登录后台",
            }
        )

    client = get_wechat_client()

    try:
        result = await client.is_online()

        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "online": result["online"],
                    "message": result["message"],
                    "token": client.token if result["online"] else None,
                    "login_time": client.login_time if result["online"] else 0,
                    "logout_time": client.logout_time if not result["online"] else 0,
                    "headimgurl": result.get("headimgurl", ""),
                    "nickname": result.get("nickname", ""),
                }
            }
        )
    except Exception as e:
        return JSONResponse(
            content={
                "success": False,
                "message": f"检查状态失败: {str(e)}",
            }
        )


@app.post("/wechat-logout")
async def admin_wechat_logout(request: Request):
    if not request.state.session.get("logged_in"):
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "message": "未登录后台",
            }
        )

    client = get_wechat_client()

    try:
        client.clear_cache()

        return JSONResponse(
            content={
                "success": True,
                "message": "已退出微信登录",
            }
        )
    except Exception as e:
        return JSONResponse(
            content={
                "success": False,
                "message": f"退出登录失败: {str(e)}",
            }
        )

if __name__ == "__main__":
    import uvicorn
    
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True
    )
    
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["default"]["fmt"] = "[%(asctime)s] %(levelprefix)s %(message)s"
    log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    log_config["formatters"]["access"]["fmt"] = '[%(asctime)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        log_config=log_config
    )
