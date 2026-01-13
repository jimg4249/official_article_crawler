import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import init_users, load_users
from app.middleware import ConcurrencyLimitMiddleware, PersistentSessionMiddleware
from app.routes.admin import router as admin_router
from app.routes.external import qrcode_dir, router as external_router
from app.tasks import WechatTaskRunner
from app.utils import log
from app.wechat import close_all_wechat_clients, get_wechat_client


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_users()
    log("[启动] 用户数据已初始化")

    runner = WechatTaskRunner(get_wechat_client=get_wechat_client, load_users=load_users)

    scheduler.add_job(runner.check_online_task, "interval", minutes=1, id="check_online")
    scheduler.add_job(runner.keep_alive_task, "interval", minutes=30, id="keep_alive")
    scheduler.start()
    log("[启动] 后台任务已启动 - 在线检查(每分钟) + 保活(每30分钟)")

    yield

    scheduler.shutdown()
    await close_all_wechat_clients()
    log("[关闭] 服务已停止")


app = FastAPI(
    title="微信公众号文章爬虫",
    description="获取微信公众号文章列表的API服务",
    version="1.0.0",
    lifespan=lifespan,
)

# 中间件
app.add_middleware(PersistentSessionMiddleware)
app.add_middleware(ConcurrencyLimitMiddleware)

# 静态资源
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/qrcodes", StaticFiles(directory=str(qrcode_dir)), name="qrcodes")

# 路由
app.include_router(external_router)
app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["default"]["fmt"] = "[%(asctime)s] %(levelprefix)s %(message)s"
    log_config["formatters"]["default"]["datefmt"] = "%Y-%m-%d %H:%M:%S"
    log_config["formatters"]["access"]["fmt"] = '[%(asctime)s] %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    log_config["formatters"]["access"]["datefmt"] = "%Y-%m-%d %H:%M:%S"

    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=log_config)

