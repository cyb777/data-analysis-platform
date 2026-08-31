"""邮件工具：发送验证码 / 通知邮件。"""
from langchain.tools import tool
from loguru import logger
import smtplib
from email.mime.text import MIMEText
import os
from dotenv import load_dotenv

from app.ai.schema.email_schema import EmailSchema

load_dotenv()


@tool("send_email", args_schema=EmailSchema)
def send_email(to: str, subject: str, content: str) -> str:
    """发送邮件（验证码 / 报表 / 通知）。收件人地址、主题、正文三个参数。"""
    try:
        msg = MIMEText(content)
        msg["to"] = to
        msg["from"] = os.getenv("EMAIL_FROM")
        msg["subject"] = subject

        smtp = smtplib.SMTP_SSL(os.getenv("EMAIL_HOST"), 465)
        smtp.login(os.getenv("EMAIL_FROM"), os.getenv("EMAIL_PASSWORD"))
        smtp.sendmail(msg["from"], msg["to"], msg.as_string())
        smtp.quit()
        logger.info(f"邮件发送成功 → {to}")
        return "邮件发送成功"
    except Exception as e:
        logger.error(f"邮件发送失败：{e}")
        return "邮件发送失败"
