"""登录 / 注册接口的参数结构（FastAPI 自动校验前端 POST 的 JSON）。"""
from pydantic import BaseModel, Field


class SendCodeSchema(BaseModel):
    """登录：发送验证码入参"""
    email: str = Field(..., example="邮箱")


class LoginSchema(BaseModel):
    """登录入参：邮箱 + 验证码"""
    email: str = Field(..., example="邮箱")
    code: str = Field(..., example="验证码")


class RegisterCodeSchema(BaseModel):
    """注册：发送验证码入参"""
    email: str = Field(..., example="邮箱")


class RegisterSchema(BaseModel):
    """注册入参：邮箱 + 验证码"""
    email: str = Field(..., example="邮箱")
    code: str = Field(..., example="验证码")
