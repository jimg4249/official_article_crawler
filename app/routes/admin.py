import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth import (
    change_password,
    create_user,
    delete_user,
    is_admin,
    load_notification_config,
    load_users,
    save_notification_config,
    verify_user,
)
from app.models import ChangePasswordRequest, LoginRequest, NotificationConfigRequest, UserCreateRequest
from app.wechat import get_wechat_client

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def admin_login(request: Request, login_data: LoginRequest):
    username = login_data.username
    password = login_data.password

    if verify_user(username, password):
        request.state.session["user"] = username
        request.state.session["logged_in"] = True
        return JSONResponse(content={"success": True, "message": "登录成功"})
    return JSONResponse(status_code=401, content={"success": False, "message": "用户名或密码错误"})


@router.get("/logout")
async def admin_logout(request: Request):
    request.state.session.clear()
    return RedirectResponse(url="/", status_code=302)


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/", status_code=302)

    username = request.state.session.get("user")
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "username": username,
            "is_admin": is_admin(username) if username else False,
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/", status_code=302)
    username = request.state.session.get("user")
    if not username or not is_admin(username):
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("user_management.html", {"request": request})


@router.get("/api/users")
async def admin_list_users(request: Request):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录"})
    username = request.state.session.get("user")
    if not username or not is_admin(username):
        return JSONResponse(status_code=403, content={"success": False, "message": "无权限"})

    data = load_users()
    users = [{"username": u.get("username", ""), "is_admin": bool(u.get("is_admin"))} for u in data.get("users", [])]
    return JSONResponse(content={"success": True, "users": users})


@router.post("/api/users")
async def admin_create_user(request: Request, body: UserCreateRequest):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录"})
    username = request.state.session.get("user")
    if not username or not is_admin(username):
        return JSONResponse(status_code=403, content={"success": False, "message": "无权限"})

    ok, msg = create_user(body.username, body.password, is_admin_user=False)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return JSONResponse(content={"success": True, "message": msg})


@router.delete("/api/users/{target_username}")
async def admin_delete_user(request: Request, target_username: str):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录"})
    username = request.state.session.get("user")
    if not username or not is_admin(username):
        return JSONResponse(status_code=403, content={"success": False, "message": "无权限"})
    if target_username == "admin":
        return JSONResponse(status_code=400, content={"success": False, "message": "不允许删除 admin"})

    ok, msg = delete_user(target_username)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return JSONResponse(content={"success": True, "message": msg})


@router.get("/change-password", response_class=HTMLResponse)
async def admin_change_password_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("change_password.html", {"request": request})


@router.post("/change-password")
async def admin_change_password(request: Request, password_data: ChangePasswordRequest):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录，请先登录"})

    username = request.state.session.get("user")
    success, message = change_password(username, password_data.old_password, password_data.new_password)
    if success:
        return JSONResponse(content={"success": True, "message": message})
    return JSONResponse(status_code=400, content={"success": False, "message": message})


@router.get("/notification-config")
async def admin_notification_config_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/", status_code=302)

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header:
        username = request.state.session.get("user")
        config = load_notification_config(username)
        return JSONResponse(content={"success": True, "config": config})
    return templates.TemplateResponse("notification_config.html", {"request": request})


@router.post("/notification-config")
async def save_notification_config_route(request: Request, config_data: NotificationConfigRequest):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录，请先登录"})

    username = request.state.session.get("user")
    config = {
        "selected_type": config_data.selected_type,
        "dingtalk": {"webhook_url": config_data.dingtalk.webhook_url, "secret": config_data.dingtalk.secret},
        "wecom": {"webhook_url": config_data.wecom.webhook_url, "secret": config_data.wecom.secret},
        "feishu": {"webhook_url": config_data.feishu.webhook_url, "secret": config_data.feishu.secret},
    }
    save_notification_config(username, config)
    return JSONResponse(content={"success": True, "message": "通知配置已保存"})


@router.get("/wechat-login", response_class=HTMLResponse)
async def admin_wechat_login_page(request: Request):
    if not request.state.session.get("logged_in"):
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("wechat_login.html", {"request": request})


@router.get("/wechat-qrcode")
async def admin_wechat_qrcode(request: Request):
    if not request.state.session.get("logged_in"):
        raise HTTPException(status_code=401, detail="未登录后台")

    username = request.state.session.get("user")
    client = get_wechat_client(username)
    try:
        qrcode_bytes = await client.init_login()
        return Response(content=qrcode_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取二维码失败: {str(e)}")


@router.post("/wechat-status")
async def admin_wechat_status(request: Request):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录后台"})

    username = request.state.session.get("user")
    client = get_wechat_client(username)

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
                },
            }
        )
    except Exception as e:
        return JSONResponse(content={"success": False, "message": f"检查状态失败: {str(e)}"})


@router.post("/wechat-logout")
async def admin_wechat_logout(request: Request):
    if not request.state.session.get("logged_in"):
        return JSONResponse(status_code=401, content={"success": False, "message": "未登录后台"})

    username = request.state.session.get("user")
    client = get_wechat_client(username)

    try:
        client.clear_cache()
        return JSONResponse(content={"success": True, "message": "已退出微信登录"})
    except Exception as e:
        return JSONResponse(content={"success": False, "message": f"退出登录失败: {str(e)}"})

