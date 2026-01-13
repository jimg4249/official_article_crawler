import time
from datetime import datetime

from app.notification import NotificationSender
from app.utils import get_cache_dir, load_json_file, log


class WechatTaskRunner:
    """
    把原本 main.py 里“离线通知/在线检查/保活”的逻辑收拢到一个类里，
    便于测试与复用，main.py 只负责调度。
    """

    def __init__(self, *, get_wechat_client, load_users):
        self.get_wechat_client = get_wechat_client
        self.load_users = load_users
        self.last_notification_time_by_user: dict[str, int] = {}

    async def send_offline_notification(self, username: str):
        try:
            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"【公众号离线通知】\n公众号已离线，请及时登录。\n检测时间：{current_time_str}"

            notification_config_file = get_cache_dir() / "notification_config.json"
            all_configs = load_json_file(notification_config_file, default=None)

            if not all_configs:
                log("[离线通知] 未找到通知配置文件，跳过通知")
                return

            config = all_configs.get(username)
            if not config:
                log(f"[离线通知] 用户 {username} 未配置通知，跳过")
                return

            selected_type = config.get("selected_type")
            if not selected_type:
                log(f"[离线通知] 用户 {username} 未配置通知类型，跳过")
                return

            robot_config = config.get(selected_type, {})
            webhook_url = robot_config.get("webhook_url", "")
            secret = robot_config.get("secret", "")

            if not webhook_url:
                log(f"[离线通知] 用户 {username} 未配置 {selected_type} Webhook，跳过")
                return

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

    async def check_online_task(self):
        data = self.load_users()
        usernames = [u.get("username") for u in data.get("users", []) if u.get("username")]

        for username in usernames:
            client = self.get_wechat_client(username)
            if not client.token:
                continue
            try:
                result = await client.is_online()
                if result["online"]:
                    continue

                log(f"[在线检查] 用户 {username} 会话已离线: {result['message']}")
                if not client.logout_time:
                    client.logout_time = int(time.time())
                    log(f"[在线检查] 用户 {username} 已记录退出时间")

                current_time = int(time.time())
                last_time = self.last_notification_time_by_user.get(username, 0)
                time_since_last = current_time - last_time

                if time_since_last >= 60 * 10:
                    await self.send_offline_notification(username)
                    self.last_notification_time_by_user[username] = current_time
                    log(f"[在线检查] 用户 {username} 已发送离线通知")
                else:
                    remaining = 600 - time_since_last
                    log(f"[在线检查] 用户 {username} 距离上次通知不足10分钟，跳过（还需等待 {remaining} 秒）")
            except Exception as e:
                log(f"[在线检查] 用户 {username} 检查异常: {e}")

    async def keep_alive_task(self):
        data = self.load_users()
        usernames = [u.get("username") for u in data.get("users", []) if u.get("username")]

        for username in usernames:
            client = self.get_wechat_client(username)
            if not client.token:
                continue
            try:
                success = await client.keep_alive()
                if success:
                    log(f"[保活任务] 用户 {username} 会话保活成功")
                else:
                    log(f"[保活任务] 用户 {username} 会话保活失败，可能需要重新登录")
            except Exception as e:
                log(f"[保活任务] 用户 {username} 保活异常: {e}")

