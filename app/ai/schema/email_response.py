"""登录验证码智能体（SystemAgent）的结构化输出结构。

规定智能体最后必须输出这个结构，代码才能稳定地拿到 code/msg/verification_code。
"""
from pydantic import BaseModel, Field


class EmailResponse(BaseModel):
    """SystemAgent 的返回：状态码 + 提示 + 验证码"""
    code: int = Field(..., description="状态码：200 发送成功，500 失败")
    msg: str = Field(..., description="提示信息")
    verification_code: str = Field(default="", description="验证码（失败时为空字符串）")
