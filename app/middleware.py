import json
import secrets
import time
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware

# 并发限制：与旧实现保持一致
request_semaphore = __import__("asyncio").Semaphore(5)


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        async with request_semaphore:
            return await call_next(request)


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

    async def dispatch(self, request, call_next):
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

