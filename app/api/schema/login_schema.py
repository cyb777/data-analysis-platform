# 登录 / 账号接口的参数结构
# FastAPI 接口的入参结构：前端 POST 过来的 JSON 会被自动校验成这里定义的结构
# 无验证码/注册结构——账号由员工数据预置（初始密码 123456），无公开注册
from pydantic import BaseModel, Field


class LoginSchema(BaseModel):
    """登录入参：员工编号 + 密码"""
    employee_id: int = Field(..., example=2020000101, description="员工编号（入职年+区域+部门+序号）")
    password: str = Field(..., example="123456")


class ChangePasswordSchema(BaseModel):
    """改密码入参：旧密码 + 新密码（接口要求携带 JWT）"""
    old_password: str = Field(..., example="123456")
    new_password: str = Field(..., min_length=6, example="newpass123", description="至少 6 位")


class BindEmailSchema(BaseModel):
    """绑定/更改收邮件邮箱入参（接口要求携带 JWT）；邮箱在 employee 表上 UNIQUE"""
    email: str = Field(..., example="zhangsan@example.com", description="收邮件用邮箱，不是登录凭证")
