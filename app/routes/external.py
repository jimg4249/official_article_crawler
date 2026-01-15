import base64
import os
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import create_user, get_user_by_username
from app.models import ArticlesByUrlRequest, RegisterRequest, WechatApiAuthRequest
from app.wechat import get_wechat_client

router = APIRouter()


def _check_api_token(api_token: str | None) -> tuple[bool, str]:
    token_env = os.getenv("API_TOKEN")
    if token_env is not None and token_env != "" and token_env != api_token:
        return False, "密钥不正确"
    return True, ""


def _require_username(username: str | None) -> tuple[bool, str, str]:
    u = (username or "").strip()
    if not u:
        return False, "需要提供 username", ""
    # 外部接口只用 API_TOKEN 鉴权，但仍需要存在账号来定位公众号会话
    if not get_user_by_username(u):
        return False, "账号不存在，请先调用 /api/register 注册", ""
    return True, "", u


@router.post("/articles-by-url")
async def get_articles_by_url(request: ArticlesByUrlRequest):
    ok, msg = _check_api_token(request.api_token)
    if not ok:
        return {"success": False, "message": msg}

    ok, msg, wechat_username = _require_username(request.username)
    if not ok:
        return {"success": False, "message": msg}

    client = get_wechat_client(wechat_username)
    if not client.token:
        return {
            "success": False,
            "message": f"未登录，请先用账号 {wechat_username} 扫码登录公众号",
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
            },
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"获取文章列表失败: {str(e)}",
            "biz": biz,
        }


@router.post("/api/wechat/qrcode")
async def api_wechat_qrcode(request: Request, body: WechatApiAuthRequest):
    ok, msg = _check_api_token(body.api_token)
    if not ok:
        return JSONResponse(status_code=401, content={"success": False, "message": msg})

    ok, msg, wechat_username = _require_username(body.username)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})

    client = get_wechat_client(wechat_username)
    try:
        qrcode_bytes = await client.init_login()
        qrcode_base64 = base64.b64encode(qrcode_bytes).decode("ascii")
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "qrcode_base64": qrcode_base64,
                },
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"获取二维码失败: {str(e)}"})


@router.post("/api/wechat/status")
async def api_wechat_status(body: WechatApiAuthRequest):
    ok, msg = _check_api_token(body.api_token)
    if not ok:
        return JSONResponse(status_code=401, content={"success": False, "message": msg})

    ok, msg, wechat_username = _require_username(body.username)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})

    client = get_wechat_client(wechat_username)
    try:
        result = await client.is_online()
        online = bool(result.get("online"))
        login_time = int(client.login_time or 0) if online else 0
        logout_time = int(client.logout_time or 0) if not online else 0

        duration_seconds = 0
        duration_text = ""
        if online and login_time:
            duration_seconds = max(0, int(time.time()) - login_time)
            h = duration_seconds // 3600
            m = (duration_seconds % 3600) // 60
            s = duration_seconds % 60
            if h > 0:
                duration_text = f"{h}小时{m}分{s}秒"
            elif m > 0:
                duration_text = f"{m}分{s}秒"
            else:
                duration_text = f"{s}秒"

        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "online": online,
                    "message": result.get("message", ""),
                    "nickname": result.get("nickname", ""),
                    "headimgurl": result.get("headimgurl", ""),
                    "login_time": login_time,
                    "logout_time": logout_time,
                    "login_duration_seconds": duration_seconds,
                    "login_duration_text": duration_text,
                },
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": f"检查状态失败: {str(e)}"})


@router.post("/api/register")
async def api_register(body: RegisterRequest):
    ok, msg = _check_api_token(body.api_token)
    if not ok:
        return JSONResponse(status_code=401, content={"success": False, "message": msg})

    username = (body.username or "").strip()
    password = (body.password or "").strip() or "123456"

    existed = get_user_by_username(username)
    if existed:
        return JSONResponse(
            content={
                "success": True,
                "data": {
                    "username": existed.get("username", username),
                    "is_admin": bool(existed.get("is_admin")) or existed.get("username") == "admin",
                },
            }
        )

    ok, msg = create_user(username, password, is_admin_user=False)
    if not ok:
        # 幂等：如果并发下刚好已存在，也直接返回账号信息
        existed = get_user_by_username(username)
        if existed:
            return JSONResponse(
                content={
                    "success": True,
                    "data": {
                        "username": existed.get("username", username),
                        "is_admin": bool(existed.get("is_admin")) or existed.get("username") == "admin",
                    },
                }
            )
        return JSONResponse(status_code=400, content={"success": False, "message": msg})

    created = get_user_by_username(username) or {"username": username, "is_admin": False}
    return JSONResponse(
        content={
            "success": True,
            "data": {
                "username": created.get("username", username),
                "is_admin": bool(created.get("is_admin")),
            },
        }
    )

