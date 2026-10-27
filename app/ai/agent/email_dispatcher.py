# EmailDispatcher 邮件调度器（supervisor 形态）
# 写作 agent 一封成稿：自己写 SQL 取数（sql_query/describe_table 裸工具——邮件链路扁平化，
# 不再过 SQLQuestionAgent，每次取数省 2 次 LLM 调用）+ 分析/检索两 Agent-as-Tool；
# response_format 结构化输出 EmailDraft（主题/收件人/正文三字段），编排层拿去即用，不做文本解析。
# 口径资料：prepare 起草时对原问题做一次 RAG 检索（business 段）注入消息，替代旧的逐问检索。
# 编排层只剩两件事：
#   prepare：调 agent → 拿结构化草稿 → 查邮箱+校验（查无此人/未绑即起草失败）
#   send：用户点确认后直接群发草稿确认集 + 留痕
# 确认集=展示集：卡片上看到的收件人就是实际发送对象（草稿即校验）。
# 草稿全程在服务端 checkpointer，/chat/resume 只回传 confirm bool 客户端改不了，send 不重查。
# 收件人无类型分类：position/employee_name 一条 OR 查询覆盖，哪列命中就是哪种发法。
#
# 本文件按流水线排序：① 成稿 prompt → ② 收件人查邮箱 → ③ 调度器（prepare/send）
from loguru import logger
from langchain.agents import create_agent

from app.ai.agent.registry import invoke_with_structured_retry
from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import query_all, sql_query_tool, describe_table_tool
from app.ai.schemas.llm_email_schema import EmailDraft
from app.ai.rag.retriever import build_metric_block
from app.ai.tool.email_material_tool import (
    analyze_material_tool, search_hotel_knowledge_tool,
    send_email_direct,
)


# ① 成稿：写作 agent 的 system prompt
# ===================================
#    素材收集自主判断 + 收件人判定（输出字段口径由 EmailDraft 的 Field 说明承载，不在这里喊话）
#    发信链路仅经理级可达（route 权限门 level>=3），写作 agent 挂四工具、工具不分档
_WRITER_PROMPT = """
一:你是邮件写作智能体：收集素材 → 写成一封可直接发送的正式经营邮件。
二:四个工具，按需调用，不是每个都要用：
    1. sql_query：执行只读 SQL 查经营数据（可用表和列名见工具说明）。
       要查多项时一轮里把几条 SQL 一起发出来，不要一句一句查
    2. describe_table：列名不确定时查表的实际列名
    3. analyze_material：把资料交给分析智能体出趋势/原因/建议（用户明确要分析结论时才调，
       参数=分析问题 + 已查到的资料原文）
    4. search_hotel_knowledge：查业务知识库（制度、流程、SOP、口径、管理方法）
三:SQL 写法：
    1. 只能 SELECT；多表用 join；GROUP BY 严格匹配 SELECT 非聚合列
    2. 时间过滤用区间比较（>= 开始 AND < 结束），不要用 DATE(列) 包裹——会废掉索引全表扫描
    3. 用户没指定时间范围时默认按最近30天统计，并在结果里注明；TOP N 用 ORDER BY + LIMIT
    4. 指标口径以消息里注入的【指标口径与查询规范】为准（其中 SQL 模板仅做参考，按实际问题改写）
四:素材规则：
    1. 对话历史里已有的素材直接引用，不要重复调工具查
    2. 纯转告/问候类可以一个工具都不调，直接写
    3. 素材取不到时直说取不到——不要编造任何数字
    4. 够用就写——工具调用越少越好
五:收件人判定：
    明说职位/人名/邮箱的直接取（"发给店长"→店长）；"老板"按"分公司老板"；
    "他/上次那位/再发一份"等指代，从对话历史里还原；问题没提时按内容推断
    （经营报告→分公司老板，差评/投诉→店长，餐饮相关→餐饮经理）；实在推断不出填"分公司老板"。
六:成稿要求（输出字段的口径见 response_format 的字段说明）：
    1. 严禁任何过程性、元信息内容：不写「处理步骤」「分析思路」之类的标题，
       不描述你是怎么取数、怎么算的
    2. 不写发送状态、「请确认」等发送流程信息
"""


# ② 查邮箱：收件人 → 邮箱列表（起草时一次查全：校验 + 卡片展示）
# ==============================================================
#    发信门槛在 route 收口（仅经理级可达），这里只查"有没有这个人、有没有邮箱"——
#    拦截话术只讲事实：不是员工 / 没有邮箱，不解释规则、不教用户做事
def _lookup_emails(value: str) -> tuple[list, list, str]:
    """收件人 → (邮箱列表, 未绑名单, 拦截原因)。err 非空即起草失败；err 空则邮箱列表必非空。
    职位/姓名不分类型：`position=%s OR employee_name=%s` 一条查询，哪列命中就是哪种发法。
    """
    # 邮箱直发：格式不预检，发不出去 SMTP 自然失败留痕
    if "@" in (value or ""):
        return [value], [], ""

    # 在职过滤不是权限是业务兜底：离职员工邮箱大概率已回收
    rows = query_all(
        "SELECT employee_name, email FROM employee "
        "WHERE employee_status='在职' AND (position=%s OR employee_name=%s)", (value, value))
    if not rows:
        return [], [], f"「{value}」不是系统内的员工或职位"
    recipients = [r[1] for r in rows if r[1]]
    no_email = [r[0] for r in rows if not r[1]]
    if not recipients:
        return [], [], (f"「{value}」没有绑定邮箱"
                        if len(rows) == 1 else f"「{value}」的人都没有绑定邮箱")
    return recipients, no_email, ""


# ③ 调度器本体：prepare（成稿→查邮箱校验）→ send（确认后群发留痕）
# ================================================================
class EmailDispatcher:
    """邮件调度器（supervisor）：写作 agent 结构化成稿 → 起草即校验 → 确认后群发留痕"""

    def __init__(self):
        logger.info("EmailDispatcher（邮件调度器）初始化")
        self._writer = None  # 写作 agent 懒建单例，见 _get_writer

    def _get_writer(self):
        """写作 agent 单例（懒建）：四工具全量挂载（直查 SQL 两件 + 分析/检索）——
        发信链路仅经理级可达（route 权限门 level>=3），工具不分档。
        response_format=EmailDraft：成稿直接吐结构（主题/收件人/正文），放 structured_response 键。
        """
        if self._writer is None:
            self._writer = create_agent(
                model=MyModel.get_model(),
                tools=[sql_query_tool, describe_table_tool, analyze_material_tool, search_hotel_knowledge_tool],
                system_prompt=_WRITER_PROMPT,
                response_format=EmailDraft,
            )
            logger.info("EmailDispatcher 写作 agent 建成（直查 SQL 四工具）")
        return self._writer

    def prepare(self, question: str, history_text: str = "") -> dict:
        """HITL 第一段：调写作 agent 拿结构化草稿 → 查邮箱，产出草稿但不发送。
        起草即校验：查无此人/全未绑直接失败——确认卡片所见即所发，不给用户看发不了的草稿。
        （发信门槛在 route 收口，这里不重复权限判断）
        """
        try:
            # 口径/规范资料一次性注入（business 段 RAG 检索）；表列全量字典在 sql_query 工具说明里
            metric_block = build_metric_block(question)
            content = (f"【对话历史】\n{history_text or '（无历史对话）'}\n\n"
                       f"【用户问题】\n{question}\n\n{metric_block}")
            writer = self._get_writer()
            # 缺结构/异常统一重试 3 次，失败返回 error 交用户重试
            draft, err = invoke_with_structured_retry(writer, content, label="EmailDispatcher")
            if draft is None:
                return {"error": f"邮件起草失败：{err}，请重试"}

            rvalue = draft.recipient.strip() or "分公司老板"  # 兜底与 prompt 第三节一致
            recipients, no_email, err = _lookup_emails(rvalue)
            if err:
                logger.info(f"EmailDispatcher 起草拦截：{err}")
                return {"error": err}
            logger.info(f"EmailDispatcher 成稿：收件人={rvalue}，命中 {len(recipients)} 人"
                        + (f"，未绑邮箱 {len(no_email)} 人" if no_email else ""))
            return {
                "recipients": recipients,
                "subject": draft.subject.strip(),
                "content": draft.content.strip(),
                "recipient_value": rvalue,   # send 群发摘要显示用
                "no_email": no_email,        # 未绑邮箱名单（确认卡片提醒"这些人收不到"）
                # @ 直放地址没过员工库校验（可能是外部邮箱/拼错的地址），确认卡黄色提醒核对
                "external": recipients if "@" in rvalue else [],
            }
        except Exception as e:
            logger.error(f"EmailDispatcher 起草失败：{e}")
            return {"error": f"邮件起草失败：{str(e)}"}

    def send(self, draft: dict, user_id: int) -> dict:
        """HITL 第二段：用户确认后直接群发草稿里的收件人集 + 留痕。
        收件人在 prepare 已校验、确认卡片已展示（所见即所发）；草稿全程在服务端 checkpointer，
        /chat/resume 只回传 confirm bool 客户端改不了，这里不重复校验。
        :param draft: prepare() 的产出（从 state.email_draft 取出来，原样传入）
        :param user_id: 发起人（写 notification_record.triggered_by）
        :return: {"sent_count": int, "recipients": list[str], "subject": str, "summary": str}
        """
        subject = draft.get("subject", "")
        recipients = draft.get("recipients", [])
        rvalue = draft.get("recipient_value", "")
        logger.info(f"EmailDispatcher 群发 {len(recipients)} 人（{rvalue}）")

        # send_email_direct 内部已吞异常返回 bool，这里只统计，不再兜底
        sent_count, sent_recipients = 0, []
        for to_email in recipients:
            if send_email_direct(
                to=to_email,
                subject=subject,
                content=draft.get("content", ""),
                notification_type="report",       # 场景=经营报表（其他场景可传 risk_alert/reminder/催办）
                trigger_source="email_dispatcher",  # 标记"系统调度器自动发"
                triggered_by=user_id,             # 触发人：发起这次调度的用户 id
            ):
                sent_count += 1
                sent_recipients.append(to_email)
        # 一封都没发出去不是"已发送"：补 failed 标志，前端渲染灰色失败卡（与起草失败同态），
        # 否则 summary"已发送至 0/N 位"会被当成绿色成功卡误导
        if recipients and sent_count == 0:
            return {
                "sent_count": 0,
                "recipients": [],
                "subject": subject,
                "summary": f"发送失败：{len(recipients)} 位收件人（{rvalue}）均未送达，请检查邮件服务后重试",
                "failed": True,
            }
        return {
            "sent_count": sent_count,
            "recipients": sent_recipients,
            "subject": subject,
            "summary": f"邮件已发送至 {sent_count}/{len(recipients)} 位收件人（{rvalue}）",
        }
