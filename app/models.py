from pydantic import BaseModel, Field
from typing import Optional

class StatusResponse(BaseModel):
    online: bool
    token: Optional[str] = None
    message: str = ""

class ArticleListRequest(BaseModel):
    fakeid: str = Field(..., description="公众号的fakeid")
    begin: int = Field(default=0, ge=0, description="起始位置")
    count: int = Field(default=5, ge=1, le=20, description="每页数量")

class ExtractBizRequest(BaseModel):
    url: str = Field(..., description="公众号文章链接")
class ArticlesByUrlRequest(BaseModel):
    api_token: str | None = Field(default=None, description="鉴权密钥")
    username: str | None = Field(default=None, description="后台账号")
    password: str | None = Field(default=None, description="后台密码")
    url: str = Field(..., description="公众号文章链接")
    number: int = Field(default=20, ge=1, description="需要获取的文章总条数")

class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="登录密码")

class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., description="新密码")

class RobotConfig(BaseModel):
    webhook_url: str = Field(default="", description="Webhook地址")
    secret: Optional[str] = Field(default="", description="Secret密钥（企微不需要）")
class NotificationConfigRequest(BaseModel):
    selected_type: str = Field(default="dingtalk", description="当前选中的通知方式")
    dingtalk: RobotConfig = Field(default_factory=RobotConfig, description="钉钉机器人配置")
    wecom: RobotConfig = Field(default_factory=RobotConfig, description="企微机器人配置")
    feishu: RobotConfig = Field(default_factory=RobotConfig, description="飞书机器人配置")

class UserCreateRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")

class WechatApiAuthRequest(BaseModel):
    api_token: str | None = Field(default=None, description="鉴权密钥")
    username: str | None = Field(default=None, description="后台账号")
    password: str | None = Field(default=None, description="后台密码")

class RegisterRequest(BaseModel):
    api_token: str | None = Field(default=None, description="鉴权密钥")
    username: str = Field(..., description="要注册的账号")
    password: str | None = Field(default=None, description="密码（为空则默认 123456）")
