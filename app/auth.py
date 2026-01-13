import base64
import hashlib
import hmac
import secrets
from typing import Optional
from app.utils import get_cache_dir, load_json_file, save_json_file

USER_DATA_FILE = get_cache_dir() / "users.json"
NOTIFICATION_CONFIG_FILE = get_cache_dir() / "notification_config.json"

PBKDF2_ITERATIONS = 200_000

def _pbkdf2_sha256(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

def hash_password(password: str) -> str:
    """
    统一密码存储格式：
    pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
    """
    salt = secrets.token_bytes(16)
    dk = _pbkdf2_sha256(password, salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256$%d$%s$%s" % (
        PBKDF2_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(dk).decode("ascii").rstrip("="),
    )

def _verify_password(stored: str, password: str) -> bool:
    # 兼容旧版 sha256(64 hex) 存储
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return hashlib.sha256(password.encode()).hexdigest() == stored

    if not stored.startswith("pbkdf2_sha256$"):
        return False

    try:
        _, iter_str, salt_b64, hash_b64 = stored.split("$", 3)
        iterations = int(iter_str)
        # urlsafe_b64decode 需要补齐 padding
        salt_pad = "=" * (-len(salt_b64) % 4)
        hash_pad = "=" * (-len(hash_b64) % 4)
        salt = base64.urlsafe_b64decode(salt_b64 + salt_pad)
        expected = base64.urlsafe_b64decode(hash_b64 + hash_pad)
        actual = _pbkdf2_sha256(password, salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def init_users():
    if not USER_DATA_FILE.exists():
        default_user = {
            "username": "admin",
            "password": hash_password("123456"),
            "is_admin": True,
        }
        save_json_file(USER_DATA_FILE, {"users": [default_user]})
        return

    # 兼容历史 users.json：若 admin 缺少 is_admin 字段，自动补齐
    data = load_json_file(USER_DATA_FILE, default={"users": []})
    changed = False
    for user in data.get("users", []):
        if user.get("username") == "admin" and "is_admin" not in user:
            user["is_admin"] = True
            changed = True
    if changed:
        save_json_file(USER_DATA_FILE, data)

def load_users() -> dict:
    init_users()
    return load_json_file(USER_DATA_FILE, default={"users": []})

def save_users(data: dict):
    save_json_file(USER_DATA_FILE, data)

def verify_user(username: str, password: str) -> bool:
    data = load_users()

    for user in data.get("users", []):
        if user.get("username") != username:
            continue
        stored = user.get("password", "")
        if _verify_password(stored, password):
            # 若是旧 sha256，登录成功后自动升级为 pbkdf2
            if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
                user["password"] = hash_password(password)
                save_users(data)
            return True
    return False

def change_password(username: str, old_password: str, new_password: str) -> tuple[bool, str]:
    if not verify_user(username, old_password):
        return False, "旧密码错误"

    data = load_users()
    new_password_hash = hash_password(new_password)

    for user in data.get("users", []):
        if user["username"] == username:
            user["password"] = new_password_hash
            save_users(data)
            return True, "密码修改成功"

    return False, "用户不存在"

def get_user_by_username(username: str) -> Optional[dict]:
    data = load_users()
    for user in data.get("users", []):
        if user["username"] == username:
            return user
    return None

def is_admin(username: str) -> bool:
    # 最小最稳妥：admin 永远是管理员（即使历史数据没写 is_admin）
    if username == "admin":
        return True
    user = get_user_by_username(username)
    return bool(user and user.get("is_admin"))

def create_user(username: str, password: str, is_admin_user: bool = False) -> tuple[bool, str]:
    username = (username or "").strip()
    if not username:
        return False, "用户名不能为空"
    if len(username) > 32:
        return False, "用户名过长"
    if len(password or "") < 6:
        return False, "密码至少6位"

    data = load_users()
    if any(u.get("username") == username for u in data.get("users", [])):
        return False, "用户名已存在"

    data.setdefault("users", []).append(
        {"username": username, "password": hash_password(password), "is_admin": bool(is_admin_user)}
    )
    save_users(data)
    return True, "用户创建成功"

def delete_user(username: str) -> tuple[bool, str]:
    data = load_users()
    users = data.get("users", [])
    new_users = [u for u in users if u.get("username") != username]
    if len(new_users) == len(users):
        return False, "用户不存在"
    data["users"] = new_users
    save_users(data)
    return True, "用户已删除"

def load_notification_config(username: str) -> Optional[dict]:
    configs = load_json_file(NOTIFICATION_CONFIG_FILE, default={})
    return configs.get(username)

def save_notification_config(username: str, config: dict):
    configs = load_json_file(NOTIFICATION_CONFIG_FILE, default={})
    configs[username] = config
    save_json_file(NOTIFICATION_CONFIG_FILE, configs)
