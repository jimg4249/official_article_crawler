import hashlib
from typing import Optional
from app.utils import get_cache_dir, load_json_file, save_json_file

USER_DATA_FILE = get_cache_dir() / "users.json"
NOTIFICATION_CONFIG_FILE = get_cache_dir() / "notification_config.json"

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def init_users():
    if not USER_DATA_FILE.exists():
        default_user = {
            "username": "admin",
            "password": hash_password("123456")
        }
        save_json_file(USER_DATA_FILE, {"users": [default_user]})

def load_users() -> dict:
    init_users()
    return load_json_file(USER_DATA_FILE, default={"users": []})

def save_users(data: dict):
    save_json_file(USER_DATA_FILE, data)

def verify_user(username: str, password: str) -> bool:
    data = load_users()
    password_hash = hash_password(password)

    for user in data.get("users", []):
        if user["username"] == username and user["password"] == password_hash:
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

def load_notification_config(username: str) -> Optional[dict]:
    configs = load_json_file(NOTIFICATION_CONFIG_FILE, default={})
    return configs.get(username)

def save_notification_config(username: str, config: dict):
    configs = load_json_file(NOTIFICATION_CONFIG_FILE, default={})
    configs[username] = config
    save_json_file(NOTIFICATION_CONFIG_FILE, configs)
