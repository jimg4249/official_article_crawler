import time
import hmac
import hashlib
import base64
from urllib.parse import quote_plus
import aiohttp
from app.utils import log


class NotificationSender:
    @staticmethod
    def _make_dingtalk_sign(secret: str, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = quote_plus(base64.b64encode(hmac_code))
        return sign

    @staticmethod
    def _make_feishu_sign(secret: str, timestamp: str) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            key=string_to_sign.encode('utf-8'),
            msg=b'',
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign

    @staticmethod
    async def send_dingtalk(webhook_url: str, secret: str, content: str) -> tuple[bool, str]:
        if not webhook_url or not secret or not content:
            return False, "缺少参数"

        timestamp = str(int(time.time() * 1000))
        sign = NotificationSender._make_dingtalk_sign(secret, timestamp)

        separator = '&' if '?' in webhook_url else '?'
        request_url = f"{webhook_url}{separator}timestamp={timestamp}&sign={sign}"

        data = {
            "msgtype": "text",
            "text": {"content": content}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    request_url,
                    json=data,
                    headers={"Content-Type": "application/json;charset=utf-8"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("errcode") == 0:
                        log(f"[钉钉通知] 发送成功")
                        return True, "发送成功"
                    else:
                        error_msg = result.get("errmsg", "请求失败")
                        log(f"[钉钉通知] 发送失败: {error_msg}")
                        return False, error_msg
        except Exception as e:
            log(f"[钉钉通知] 发送异常: {e}")
            return False, str(e)

    @staticmethod
    async def send_feishu(webhook_url: str, secret: str, content: str) -> tuple[bool, str]:
        if not webhook_url or not content:
            return False, "缺少参数"

        data = {
            "msg_type": "text",
            "content": {"text": content}
        }

        if secret:
            timestamp = str(int(time.time()))
            sign = NotificationSender._make_feishu_sign(secret, timestamp)
            data["timestamp"] = timestamp
            data["sign"] = sign

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=data,
                    headers={"Content-Type": "application/json;charset=utf-8"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("code") == 0:
                        log(f"[飞书通知] 发送成功")
                        return True, "发送成功"
                    else:
                        error_msg = result.get("msg", "请求失败")
                        log(f"[飞书通知] 发送失败: {error_msg}")
                        return False, error_msg
        except Exception as e:
            log(f"[飞书通知] 发送异常: {e}")
            return False, str(e)

    @staticmethod
    async def send_wecom(webhook_url: str, content: str) -> tuple[bool, str]:
        if not webhook_url or not content:
            return False, "缺少参数"

        data = {
            "msgtype": "text",
            "text": {"content": content}
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook_url,
                    json=data,
                    headers={"Content-Type": "application/json;charset=utf-8"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    result = await response.json()

                    if response.status == 200 and result.get("errcode") == 0:
                        log("[企微通知] 发送成功")
                        return True, "发送成功"
                    else:
                        error_msg = result.get("errmsg", "请求失败")
                        log(f"[企微通知] 发送失败: {error_msg}")
                        return False, error_msg
        except Exception as e:
            log(f"[企微通知] 发送异常: {e}")
            return False, str(e)

    @staticmethod
    async def send_notification(notification_type: str, webhook_url: str, secret: str, content: str) -> tuple[bool, str]:
        if notification_type == "dingtalk":
            return await NotificationSender.send_dingtalk(webhook_url, secret, content)
        elif notification_type == "feishu":
            return await NotificationSender.send_feishu(webhook_url, secret, content)
        elif notification_type == "wecom":
            return await NotificationSender.send_wecom(webhook_url, content)
        else:
            return False, f"不支持的通知类型: {notification_type}"
