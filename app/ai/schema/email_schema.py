# 邮件工具入参结构
# Pydantic 数据模型：定义"数据长什么样"，用来做输入校验和格式约束
#   BaseModel：Pydantic 的基类，声明字段后自动校验类型
#   Field(..., description="...")：字段定义，... 表示必填，description 是给模型看的说明
from pydantic import BaseModel, Field


class EmailSchema(BaseModel):
    """send_email 工具的参数：收件人 + 主题 + 正文"""
    to: str = Field(..., description="收件人邮箱地址")
    subject: str = Field(..., description="邮件主题")
    content: str = Field(..., description="邮件内容")
