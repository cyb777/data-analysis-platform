# 邮件工具：一个文件装下邮件相关的全部代码。
# 一、素材工具两件套（@tool）：分析/检索的 Agent-as-Tool 包装层。
# 为什么要有这层包装（@tool 只能装饰函数，agent 是 class 装饰不上去）：
#   1. 收敛签名：agent.answer 的多参数是内部实现，不暴露给调用的 LLM——包装后 LLM 只看到干净的参数
#   2. docstring 即工具说明：LLM 靠它判断"什么时候该调哪个工具"
#   3. 收拢配套动作：知识检索固定 hotel tag、异常降级
# 取数没有包装层：写作 agent 直接挂 sql_query/describe_table 裸工具（邮件链路扁平化——
# 表列全量字典在 sql_query 工具说明里，口径资料由 dispatcher 起草时一次性注入），
# 不再过 SQLQuestionAgent，每次取数省 2 次 LLM 调用。
# 分工：writer 只排版综合；数据分析（含吃上下文数据的分析）归 anlyze_agent，
# 它不自己分析——"把上下文里的经营分析写进邮件"这类活排版层干不了。
# 被包装的 anlyze_agent 本身零改动，感知不到自己成了工具。
# 注意：registry 必须在函数体内 import（调用时）——registry 顶层 import 各 agent 建单例，
# 本模块顶层再 import 回去就循环了。
# 二、发送服务（无 @tool）：SMTP 直发 + notification_record 留痕。
# 发邮件是确定性执行动作，参数（收件人/主题/正文）由上游定死，不需要 LLM 决策"发不发"，
# 挂成 @tool 反而多一层不确定，所以有意不挂。
# 发件人固定用 .env 的 EMAIL_FROM（QQ邮箱），收件人由 dispatcher 查 employee 解析（职位/姓名/邮箱均可）；
# send_email_direct 内部统一落 notification_record 留痕：
#   - 留痕字段：to_email / notification_type / subject / send_status / trigger_source / triggered_by
#   - trigger_source：email_dispatcher / manual（区分"谁触发的"）
#   - triggered_by：employee.employee_id（email_dispatcher 自动发时为调 EmailDispatcher 的那个员工）
from loguru import logger
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from langchain.tools import tool

from app.ai.rag.retriever import retrieve_schema
from app.ai.tool.mysql_tool import execute_write      # 留痕 INSERT 复用连接池 + 统一 commit

load_dotenv()


@tool("analyze_material")
def analyze_material_tool(question: str, material: str) -> str:
    """把资料交给分析智能体做经营分析，返回趋势/原因/建议类结论。
    用法：先用 sql_query 查到数据，再把结果原文传给本工具分析。
    参数：question=分析问题，material=要分析的资料原文。"""
    # 分析不看对话历史（历史由写作 agent 自己掌握、在排版时综合），
    # 避免 LLM 把长历史抄进工具参数浪费 token
    from app.ai.agent.registry import anlyze_agent
    return anlyze_agent.answer(question=question, context=material, history_text="（无）")


@tool("search_hotel_knowledge")
def search_hotel_knowledge_tool(question: str) -> str:
    """检索酒店业务知识库：制度、流程、SOP、指标口径、管理方法类内容（差评处理流程、
    收益管理方法、会员体系规则等）。参数是一句检索问题，返回知识库相关段落。"""
    try:
        # tag="hotel"：只召回业务知识段，不召表结构（表结构归 sql_query 工具说明 + dispatcher 起草注入）
        return retrieve_schema(question, tag_filter="hotel") or "（知识库未检索到相关内容）"
    except Exception as e:
        logger.warning(f"邮件素材：知识检索失败（降级无知识素材）：{e}")
        return f"（知识检索失败：{e}）"


# 发送服务（无 @tool，不进任何 agent 的工具列表）
# ===============================================

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
            "(employee_id, to_email, notification_type, subject, content, send_status, error_msg, trigger_source, triggered_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        execute_write(sql, (
            triggered_by,           # employee_id 字段（发件人=触发人员工编号）
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
) -> bool:
    """业务层直发邮件：跳过 LLM、跳过 @tool 包装，给通知/告警/经营报表用。
    返回 True=发送成功 / False=失败（成败也落 notification_record.send_status）。

    内部统一落 notification_record 留痕：
      - notification_type：report / risk_alert / reminder / 催办
      - trigger_source：email_dispatcher / manual（区分"谁触发的"）
      - triggered_by：employee.employee_id（email_dispatcher 自动发时为调 EmailDispatcher 的那个员工）
    **收件人约定**：to 由调用方从 employee 员工表解析（dispatcher._lookup_emails，职位/姓名/邮箱均可），不要硬编码邮箱。
    **场景**：酒店经营报表 / 差评投诉告警 / 经营提醒 / 催办提醒。
    """
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
    except Exception as e:
        send_status = 0
        error_msg = str(e)
        logger.error(f"邮件直发失败：{e}")

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
    return send_status == 1
