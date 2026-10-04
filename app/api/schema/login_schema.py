# 登录 / 注册接口的参数结构
# FastAPI 接口的入参结构：前端 POST 过来的 JSON 会被自动校验成这里定义的结构
#   example="邮箱"：接口文档（/docs）里显示的示例值
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
