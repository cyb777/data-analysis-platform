# 邮件工具层：通用邮件发送。
# 发件人固定用 .env 的 EMAIL_FROM（QQ邮箱），收件人从 user_info 按 role 查；
# send_email_direct 内部统一落 notification_record 留痕：
#   - 留痕字段：to_email / notification_type / subject / send_status / trigger_source / triggered_by
#   - trigger_source：email_dispatcher / manual / verify_code（区分"谁触发的"）
#   - triggered_by：user_info.id（email_dispatcher 自动发时为调 EmailDispatcher 的那个用户）
from loguru import logger
import os
import re
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

from app.ai.tool.mysql_tool import execute_write      # 留痕 INSERT 复用连接池 + 统一 commit

load_dotenv()


# LLM 产出的是 Markdown，邮件渲染成这套 HTML（收件客户端均支持 HTML，不附纯文本兜底）
_EMAIL_HTML_TEMPLATE = """<html><head><meta charset="utf-8"><style>
body{{font-family:"Microsoft YaHei",Arial;font-size:14px;line-height:1.7;color:#222}}
h1,h2,h3{{color:#1a3a6b;margin:18px 0 8px}}
table{{border-collapse:collapse;margin:10px 0}}
th,td{{border:1px solid #bbb;padding:6px 12px;text-align:center}}
th{{background:#eef3fb}}strong{{color:#c0392b}}
</style></head><body>{body}</body></html>"""


def _md_to_html(md: str) -> str:
    """Markdown 渲染成 HTML 并套样式。扩展须写完整路径（markdown 3.11 起短名不补前缀）。"""
    import markdown as md_lib
    body = md_lib.markdown(md, extensions=["markdown.extensions.tables"])
    return _EMAIL_HTML_TEMPLATE.format(body=body)


# HITL 包装行特征：草稿声明/收件人主题状态字段/确认提示/分隔线，匹配即从正文剔除
_WRAPPER_RE = re.compile(
    r"拟发送|邮件草稿|尚未发送|邮件待确认|HITL|确认后系统|请确认是否发送"
    r"|确认后将.*发送|需您.*确认|notification_record"
    r"|^\s*\*{0,2}\s*(收件人|主\s*题|状态)\s*[:：]|^\s*-{3,}\s*$"
)


def strip_email_wrapper(content: str) -> str:
    """剥掉 Agent 误写进正文的 HITL 包装（包装归前端确认卡片），正文内容不动。"""
    if not content:
        return content
    return "\n".join(l for l in content.splitlines()
                     if not _WRAPPER_RE.search(l.strip())).strip()


def _log_notification(
    to_email: str,
    subject: str,
    content: str,
    send_status: int,
    error_msg: str = "",
    notification_type: str = "report",
    trigger_source: str = "manual",
    triggered_by: int = 0,
):
    """统一邮件留痕：往 notification_record 写一条。
    失败不影响邮件发送主流程（落库失败仅打 warning）。
    走 mysql_tool 的 execute_write（连接池 + 自动 commit + 自动 close）。
    """
    try:
        sql = (
            "INSERT INTO notification_record "
            "(user_id, to_email, notification_type, subject, content, send_status, error_msg, trigger_source, triggered_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        execute_write(sql, (
            triggered_by,           # user_id 字段（兼容：原 schema 里是发件人 user_id）
            to_email,
            notification_type,
            subject,
            content[:500] if content else "",   # 仅留痕，截 500 字
            send_status,
            error_msg[:200] if error_msg else None,
            trigger_source,
            triggered_by,
        ))
        logger.info(f"邮件留痕成功 → notification_record（{to_email}, status={send_status}, source={trigger_source}）")
    except Exception as e:
        # 落库失败不阻塞主流程（邮件已经发出去了）
        logger.warning(f"notification_record 落库失败：{e}")


def send_email_direct(
    to: str,
    subject: str,
    content: str,
    notification_type: str = "report",
    trigger_source: str = "manual",
    triggered_by: int = 0,
) -> str:
    """业务层直发邮件：跳过 LLM、跳过 @tool 包装，给登录/通知/告警/经营报表用。
    返回 "邮件发送成功" / "邮件发送失败" 字符串。

    内部统一落 notification_record 留痕：
      - notification_type：verification / report / risk_alert / reminder / 催办
      - trigger_source：email_dispatcher / manual / verify_code（区分"谁触发的"）
      - triggered_by：user_info.id（email_dispatcher 自动发时为调 EmailDispatcher 的那个用户）

    **收件人约定**：从 user_info 登录账号表按 role 查（分公司老板/区域经理/店长/前厅经理/客房经理/餐饮经理），不要硬编码邮箱。
    **场景**：验证码 / 酒店经营报表 / 差评投诉告警 / 经营提醒 / 催办提醒。
    """
    # 发送前兜底剥离 HITL 包装（上游 prepare 已剥过，这里防其他入口直发时漏网）
    content = strip_email_wrapper(content)

    send_status = 0
    error_msg = ""
    try:
        sender = os.getenv("EMAIL_FROM")
        msg = MIMEText(_md_to_html(content), "html", "utf-8")
        msg["to"] = to
        msg["from"] = sender
        msg["subject"] = subject

        smtp = smtplib.SMTP_SSL(os.getenv("EMAIL_HOST"), 465)
        smtp.login(os.getenv("EMAIL_FROM"), os.getenv("EMAIL_PASSWORD"))
        smtp.sendmail(msg["from"], msg["to"], msg.as_string())
        smtp.quit()
        send_status = 1
        logger.info(f"邮件直发成功 → {to} | subject={subject}")
        result = "邮件发送成功"
    except Exception as e:
        send_status = 0
        error_msg = str(e)
        logger.error(f"邮件直发失败：{e}")
        result = "邮件发送失败"

    # 统一落留痕（无论成功失败都记）
    _log_notification(
        to_email=to,
        subject=subject,
        content=content,
        send_status=send_status,
        error_msg=error_msg,
        notification_type=notification_type,
        trigger_source=trigger_source,
        triggered_by=triggered_by,
    )
    return result
