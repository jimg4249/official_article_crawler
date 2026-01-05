import json
import re
import time
import asyncio
import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse
import os
import aiohttp
import aiohttp_socks
from email.utils import parsedate_to_datetime
from app.utils import log

class WechatClient:
    BASE_HOST = "mp.weixin.qq.com"
    BASE_URL = "https://mp.weixin.qq.com"
    CACHE_DURATION = 7 * 24 * 3600
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
    )
    
    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session: Optional[aiohttp.ClientSession] = None
        self._scan_task: Optional[asyncio.Task] = None

        self.api_password = os.getenv("API_PASSWORD")
        self.proxy_host = os.getenv("SOCKS_PROXY_HOST")
        self.proxy_port = int(os.getenv("SOCKS_PROXY_PORT", "0")) if os.getenv("SOCKS_PROXY_PORT") else None
        self.proxy_username = os.getenv("SOCKS_PROXY_USERNAME")
        self.proxy_password = os.getenv("SOCKS_PROXY_PASSWORD")

        if self.proxy_host and self.proxy_port and self.proxy_username and self.proxy_password:
            self.proxy_url = f"socks5://{self.proxy_username}:{self.proxy_password}@{self.proxy_host}:{self.proxy_port}"
            self.use_proxy = True
            log(f"[代理] 已启用SOCKS5代理 - Host: {self.proxy_host}:{self.proxy_port}")
            log(f"[代理] 代理用户名: {self.proxy_username}")
        else:
            self.proxy_url = None
            self.use_proxy = False
            log("[代理] 未配置SOCKS代理，将使用直连")
    
    def _get_cookie_cache_key(self) -> str:
        return "wechat_official_proxy_http_client_cookie"

    def _get_cache_file_path(self, key: str) -> Path:
        return self.cache_dir / f"{hashlib.md5(key.encode()).hexdigest()}.json"

    def _get_cache_data(self) -> dict:
        cache_key = self._get_cookie_cache_key()
        file_path = self._get_cache_file_path(cache_key)

        if not file_path.exists():
            return {}

        try:
            data = json.loads(file_path.read_text())
            if data.get("expire_at", 0) < time.time():
                file_path.unlink()
                return {}

            return data
        except (json.JSONDecodeError, KeyError):
            return {}

    def _set_cache_data(self, data: dict) -> None:
        cache_key = self._get_cookie_cache_key()
        file_path = self._get_cache_file_path(cache_key)
        file_path.write_text(json.dumps(data))

    def clear_cache(self) -> None:
        data = self._get_cache_data()

        data["value"] = {}
        data["token"] = None
        data["logout_time"] = int(time.time())
        data["expire_at"] = time.time() + self.CACHE_DURATION

        self._set_cache_data(data)
        log("[清除缓存] 已清空微信cookies和token")

    @property
    def token(self) -> Optional[str]:
        return self._get_cache_data().get("token")

    @token.setter
    def token(self, value: Optional[str]) -> None:
        data = self._get_cache_data()
        data["token"] = value
        data["expire_at"] = time.time() + self.CACHE_DURATION
        self._set_cache_data(data)

    @property
    def login_time(self) -> Optional[int]:
        return self._get_cache_data().get("login_time")

    @login_time.setter
    def login_time(self, value: Optional[int]) -> None:
        data = self._get_cache_data()
        data["login_time"] = value
        data["expire_at"] = time.time() + self.CACHE_DURATION
        self._set_cache_data(data)

    @property
    def logout_time(self) -> Optional[int]:
        return self._get_cache_data().get("logout_time")

    @logout_time.setter
    def logout_time(self, value: Optional[int]) -> None:
        data = self._get_cache_data()
        data["logout_time"] = value
        data["expire_at"] = time.time() + self.CACHE_DURATION
        self._set_cache_data(data)

    @property
    def cookies(self) -> dict:
        data = self._get_cache_data()
        cookies = data.get("value", {})

        current_time = time.time()
        valid_cookies = {}
        for name, cookie_data in cookies.items():
            if "expires" in cookie_data:
                if cookie_data["expires"] < current_time:
                    continue
            valid_cookies[name] = cookie_data

        return valid_cookies
    
    def _update_cookies_from_response(self, response: aiohttp.ClientResponse) -> None:
        data = self._get_cache_data()
        if "value" not in data:
            data["value"] = {}

        for cookie_name, cookie in response.cookies.items():
            cookie_data = {
                "value": cookie.value,
                "domain": cookie.get("domain", ""),
                "path": cookie.get("path", "/"),
            }

            if "expires" in cookie:
                try:
                    expires_dt = parsedate_to_datetime(cookie["expires"])
                    cookie_data["expires"] = expires_dt.timestamp()
                except Exception:
                    pass

            data["value"][cookie_name] = cookie_data

        data["expire_at"] = time.time() + self.CACHE_DURATION
        self._set_cache_data(data)
    
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            if self.use_proxy:
                connector = aiohttp_socks.SocksConnector(
                    host=self.proxy_host,
                    port=self.proxy_port,
                    username=self.proxy_username,
                    password=self.proxy_password,
                    rdns=True,
                    limit=10,
                    limit_per_host=10,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True,
                    force_close=False,
                )
                log(f"[代理] 使用SOCKS5代理连接: {self.proxy_host}:{self.proxy_port}")
            else:
                connector = aiohttp.TCPConnector(
                    limit=10, 
                    limit_per_host=10, 
                    ttl_dns_cache=300, 
                    enable_cleanup_closed=True, 
                    force_close=False,
                )
                log("[代理] 使用直连（无代理）")
            
            timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
            self._session = aiohttp.ClientSession(
                base_url=self.BASE_URL,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Referer": f"{self.BASE_URL}/",
                },
                connector=connector,
                timeout=timeout,
                trust_env=not self.use_proxy,
            )
        return self._session
    
    async def close(self) -> None:
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
    
    def _get_cookie_dict(self) -> dict[str, str]:
        return {name: cookie_data["value"] for name, cookie_data in self.cookies.items()}
    
    async def get(
        self,
        uri: str,
        params: Optional[dict] = None,
        is_ajax: bool = True,
        timeout: Optional[int] = None
    ) -> dict | bytes:
        session = await self._get_session()
        cookie_dict = self._get_cookie_dict()
        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with session.get(
                    uri,
                    params=params,
                    cookies=cookie_dict,
                    timeout=request_timeout
                ) as response:
                    self._update_cookies_from_response(response)

                    if is_ajax:
                        result = await response.json()
                        if result.get("respCode"):
                            raise Exception(f"微信接口请求异常: {result.get('respMsg', '')}")
                        return result
                    return await response.read()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == max_retries - 1:
                    log(f"[GET] 请求失败，已重试{max_retries}次: {uri[:50]}... - {type(e).__name__}")
                    raise
                log(f"[GET] 请求失败，重试第{attempt + 1}次: {type(e).__name__}")
                await asyncio.sleep(0.5 * (attempt + 1))
    
    async def post(
        self,
        uri: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        timeout: Optional[int] = None
    ) -> dict:
        session = await self._get_session()
        cookie_dict = self._get_cookie_dict()

        request_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with session.post(
                    uri,
                    params=params,
                    data=data,
                    cookies=cookie_dict,
                    timeout=request_timeout
                ) as response:
                    self._update_cookies_from_response(response)

                    result = await response.json()
                    if result.get("base_resp", {}).get("ret"):
                        raise Exception(f"微信接口请求异常: {result['base_resp'].get('err_msg', '')}")
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == max_retries - 1: 
                    log(f"[POST] 请求失败，已重试{max_retries}次: {uri[:50]}... - {type(e).__name__}")
                    raise
                log(f"[POST] 请求失败，重试第{attempt + 1}次: {type(e).__name__}")
                await asyncio.sleep(0.5 * (attempt + 1))
    
    async def init_login(self) -> bytes:
        self.token = None
        if self._scan_task and not self._scan_task.done():
            self._scan_task.cancel()
        await self.get("", is_ajax=False)
        
        prelogin_data = {
            "action": "prelogin",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        await self.post("/cgi-bin/bizlogin", data=prelogin_data)
        
        startlogin_data = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": "3",
            "token": "",
            "llang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        await self.post(
            "/cgi-bin/bizlogin", 
            params={"action": "startlogin"}, 
            data=startlogin_data
        )
        
        qrcode = await self.get(
            "/cgi-bin/scanloginqrcode",
            params={"action": "getqrcode", "random": str(int(time.time() * 1000))},
            is_ajax=False,
        )
        
        self._scan_task = asyncio.create_task(self._poll_scan_status())
        
        return qrcode
    
    async def _poll_scan_status(self) -> None:
        log("[扫码] 开始后台轮询扫码状态...")
        
        try:
            while True:
                params = {
                    "action": "ask",
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": "1",
                }
                resp = await self.get("/cgi-bin/scanloginqrcode", params=params)
                status = resp.get("status", -1)
                
                if status == 0:
                    log("[扫码] 等待扫码中...")
                elif status == 4:
                    log("[扫码] 已扫码，等待确认...")
                elif status == 6:
                    log("[扫码] 等待验证...")
                elif status == 1:
                    log("[扫码] 扫码成功，正在完成登录...")
                    success = await self._complete_login()
                    if success:
                        log("[扫码] 登录成功！")
                    else:
                        log("[扫码] 登录失败")
                    return
                else:
                    log(f"[扫码] 未知状态: {status}，停止轮询")
                    return
                
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            log("[扫码] 轮询任务被取消")
        except Exception as e:
            log(f"[扫码] 轮询异常: {e}")
    
    async def _complete_login(self) -> bool:
        login_data = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": "0",
            "cookie_cleaned": "0",
            "plugin_used": "0",
            "login_type": "3",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        resp = await self.post(
            "/cgi-bin/bizlogin", 
            params={"action": "login"}, 
            data=login_data
        )
        
        redirect_url = resp.get("redirect_url", "")
        if not redirect_url:
            return False
        
        parsed = urlparse(redirect_url)
        query_params = parse_qs(parsed.query)
        token = query_params.get("token", [""])[0]
        
        if not token:
            return False

        self.token = token
        self.login_time = int(time.time())

        await self.get(redirect_url, is_ajax=False)

        return True
    
    async def is_online(self) -> dict:
        if not self.token:
            return {"online": False, "message": "未登录", "headimgurl": "", "nickname": ""}
        
        try:
            params = {
                "action": "get_acct_list",
                "token": self.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            }
            resp = await self.get("/cgi-bin/switchacct", params=params)

            base_resp = resp.get("base_resp", {})
            if base_resp.get("ret", 0) != 0:
                self.token = None
                self.logout_time = int(time.time())
                return {"online": False, "message": "会话已过期", "headimgurl": "", "nickname": ""}

            headimgurl = ""
            nickname = ""

            service_biz_list = resp.get("service_biz_list", {}).get("list", [])
            if service_biz_list and len(service_biz_list) > 0:
                headimgurl = service_biz_list[0].get("headimgurl", "")
                nickname = service_biz_list[0].get("nickname", "")

            if not headimgurl:
                biz_list = resp.get("biz_list", {}).get("list", [])
                if biz_list and len(biz_list) > 0:
                    headimgurl = biz_list[0].get("headimgurl", "")
                    nickname = biz_list[0].get("nickname", "")

            if not headimgurl:
                wxa_list = resp.get("wxa_list", {}).get("list", [])
                if wxa_list and len(wxa_list) > 0:
                    headimgurl = wxa_list[0].get("headimgurl", "")
                    nickname = wxa_list[0].get("nickname", "")

            if not headimgurl:
                wxproduct_list = resp.get("wxproduct_list", {}).get("list", [])
                if wxproduct_list and len(wxproduct_list) > 0:
                    headimgurl = wxproduct_list[0].get("headimgurl", "")
                    nickname = wxproduct_list[0].get("nickname", "")

            return {"online": True, "message": "在线", "headimgurl": headimgurl, "nickname": nickname}
        except Exception:
            self.token = None
            self.logout_time = int(time.time())
            return {"online": False, "message": "会话已过期", "headimgurl": "", "nickname": ""}
    
    async def keep_alive(self) -> bool:
        if not self.token:
            return False

        try:
            log("[保活] 访问公众号后台首页刷新session...")
            params = {
                "t": "home/index",
                "lang": "zh_CN",
                "token": self.token,
            }
            await self.get("/cgi-bin/home", params=params, is_ajax=False)

            log("[保活] 验证token有效性...")
            result = await self.is_online()

            if result["online"]:
                log("[保活] Token验证成功，会话保持正常")
            else:
                log(f"[保活] Token验证失败: {result['message']}")

            return result["online"]
        except Exception as e:
            log(f"[保活] 保活异常: {e}")
            return False
    
    async def get_articles(
        self, 
        fakeid: str, 
        begin: int = 0, 
        count: int = 5
    ) -> dict:
        if not self.token:
            raise Exception("未登录，请先扫码登录")
        
        params = {
            "sub": "list",
            "search_field": "null",
            "begin": str(begin),
            "count": str(count),
            "query": "",
            "fakeid": fakeid,
            "type": "101_1",
            "free_publish_type": "1",
            "sub_action": "list_ex",
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        
        resp = await self.get("/cgi-bin/appmsgpublish", params=params)
        
        publish_page = resp.get("publish_page", "{}")
        if isinstance(publish_page, str):
            publish_page = json.loads(publish_page)
        
        publish_list = publish_page.get("publish_list", [])
        for item in publish_list:
            if "publish_info" in item and isinstance(item["publish_info"], str):
                item["publish_info"] = json.loads(item["publish_info"])
        
        return publish_page
    
    async def extract_biz_from_url(self, article_url: str) -> Optional[str]:
        log(f"[提取BIZ] 开始提取: {article_url[:50]}...")
        
        session = await self._get_session()
        
        try:
            log("[提取BIZ] 正在请求文章页面...")
            
            timeout = aiohttp.ClientTimeout(total=10) 
            async with session.get(
                article_url,
                headers={"User-Agent": self.USER_AGENT},
                timeout=timeout,
                allow_redirects=True,
            ) as response:
                log(f"[提取BIZ] 请求成功，状态码: {response.status}")
                log("[提取BIZ] 正在读取响应内容（流式读取前 512B）...")
                content_bytes = b""
                
                async for chunk in response.content.iter_chunked(256):
                    content_bytes += chunk
                    if len(content_bytes) >= 1024*5:
                        log(f"[提取BIZ] 已读取 {len(content_bytes)} 字节，停止读取")
                        break
                html_content = content_bytes.decode('utf-8', errors='ignore')
                log(f"[提取BIZ] 响应内容大小: {len(html_content)} 字符")
            
            log("[提取BIZ] 正在使用正则表达式搜索 biz...")
            pattern = r'biz:\s*["\']([A-Za-z0-9+/=]+)["\']'
            match = re.search(pattern, html_content)
            
            if match:
                biz = match.group(1)
                log(f"[提取BIZ] 成功提取 biz: {biz}")
                return biz
            
            log("[提取BIZ] 未找到 biz 值")
            return None
            
        except asyncio.TimeoutError as e:
            log(f"[提取BIZ] 请求超时: {article_url[:50]}... - {type(e).__name__}")
            raise Exception("请求超时，请稍后重试")
        except Exception as e:
            log(f"[提取BIZ] 提取失败 - 异常类型: {type(e).__name__}, 异常信息: {str(e) or '(空)'}")
            import traceback
            log(f"[提取BIZ] 堆栈跟踪: {traceback.format_exc()}")
            raise Exception(f"提取biz值失败: {str(e) or '未知错误'}")


# 全局客户端实例
_wechat_client: Optional[WechatClient] = None

def get_wechat_client() -> WechatClient:
    global _wechat_client
    if _wechat_client is None:
        _wechat_client = WechatClient()
    return _wechat_client
