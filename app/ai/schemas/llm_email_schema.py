# 邮件草稿结构（EmailDispatcher 写作 agent 的 response_format 结构化输出）
from pydantic import BaseModel, Field


class EmailDraft(BaseModel):
    """邮件草稿：写作 agent 成稿直接按这个结构填，编排层拿去即用，不做文本解析"""
    subject: str = Field(..., description="邮件主题，15 字以内，只保留时间和业务对象（如：上周酒店经营报告）")
    recipient: str = Field(..., description="收件人：职位名/员工姓名/邮箱地址，原文照写不解释；推断不出填「分公司老板」")
    content: str = Field(..., description="邮件正文，Markdown 排版（标题/表格/加粗），从称呼开头到落款/敬语结束，语言正式、面向管理者")
