# =========================================================
# EmailDispatcher 邮件调度器
# 显式 3 步走（不用 create_agent 黑盒，流程可控）：
#   ① 调 SQLQuestionAgent 同时查业务数据 + 收件人邮箱（一次查两样）
#   ② 调 AnlyzeAgent 把数据写成邮件正文
#   ③ 循环 send_email_direct 群发（每发一封落一条 notification_record）
# 协作模式：Agent-as-Tool（内部 import SQL/Anlyze 子智能体）
# =========================================================
from loguru import logger

from app.ai.tool.send_email_tool import send_email_direct
from app.ai.tool.rag_tool import build_schema_block


class EmailDispatcher:
    """邮件调度器：查数据 + 查收件人 → 写正文 → 群发留痕（3 步显式流程）"""

    def __init__(self):
        logger.info("EmailDispatcher（邮件调度器）初始化")

    @staticmethod
    def _sub_agents():
        """拿协作智能体（Agent-as-Tool）：复用 registry 的进程级单例，不自己 new。

        注意必须在方法里 import：registry 顶层会 import 本模块建 email_dispatcher 单例，
        模块顶层再 import 回去就循环了；调用时 import，此刻 registry 已加载完毕。
        """
        from app.ai.agent.registry import sql_agent, anlyze_agent
        return sql_agent, anlyze_agent

    def prepare(self, question: str, recipient_role: str) -> dict:
        """HITL 第一段：查数据 + 查收件人 + 写正文，产出草稿但不发送。

        :return: 草稿 dict。失败时 {"error": 原因}，调用方跳过确认直接报失败。
        """
        try:
            sql_agent, anlyze_agent = self._sub_agents()

            # 第 1 步：调 SQL 智能体同时查业务数据 + 收件人邮箱
            combined_question = (
                f"{question}\n\n"
                f"同时查出 role='{recipient_role}' 的所有用户邮箱（email 非空），把邮箱列表也整理出来。"
            )
            _, schema_block = build_schema_block(combined_question)
            data_text = sql_agent.answer(combined_question, schema_text=schema_block)
            logger.info(f"EmailDispatcher 查数据完成：{len(data_text)} 字")

            # 第 2 步：从结果里解析收件人邮箱
            recipients = self._extract_emails(data_text)
            if not recipients:
                logger.warning(f"角色 {recipient_role} 下无收件人")
                return {"error": f"未找到 role={recipient_role} 的收件人，请检查 user_info 表"}

            # 第 3 步：调分析智能体把数据写成邮件正文。
            # 用临时指令（提示词层）约束成正式邮件格式，通用 agent 本身不感知邮件场景。
            # 第一行让它顺带给主题（同一次模型调用，不再单独请求）。
            email_instruction = (
                "你在写一封要直接发给收件人的正式经营报告邮件：\n"
                "1. 第一行只写「主题：」+ 15 字以内的邮件主题（只保留时间和业务对象，"
                "去掉发邮件、发给谁、汇总等动作，如「主题：上周酒店经营报告」），"
                "第二行起才是正文；\n"
                "2. 正文直接从称呼（如「张总您好，」）开头，到落款/敬语结束；\n"
                "3. 严禁出现任何过程性、元信息内容：不要写「处理步骤」「分析思路」"
                "之类的标题，不要描述你是怎么取数、怎么算的；\n"
                "4. 不要写收件人、发送状态、「请确认」等发送流程信息；\n"
                "5. 正文用 Markdown 排版（标题/表格/加粗），语言正式、面向管理者。"
            )
            raw_output = anlyze_agent.answer(
                question=question,
                context=data_text,
                history_text="（发邮件场景，无历史对话）",
                extra_instruction=email_instruction,
            )
            # 首行是「主题：X」：取出 X 作主题，其余才是正文
            email_content, subject = self._extract_subject(raw_output)
            # 正文清洗：剥掉 Agent 可能误带的 HITL 包装（包装归前端确认卡片）
            from app.ai.tool.send_email_tool import strip_email_wrapper
            email_content = strip_email_wrapper(email_content)
            logger.info(f"EmailDispatcher 邮件正文生成完成：{len(email_content)} 字")

            return {
                "recipients": recipients,
                "subject": subject,
                "content": email_content,
                "role": recipient_role,
            }
        except Exception as e:
            logger.error(f"EmailDispatcher 起草失败：{e}")
            return {"error": f"邮件起草失败：{str(e)}"}

    def send(self, draft: dict, user_id: int) -> dict:
        """HITL 第二段：用户确认后才执行——循环 send_email_direct 群发 + 落留痕。

        :param draft: prepare() 的产出（从 state.email_draft 取出来，原样传入）
        :param user_id: 发起人（写 notification_record.triggered_by）
        :return: {"sent_count": int, "recipients": list[str], "subject": str, "summary": str}
        """
        role = draft.get("role", "")
        recipients = draft.get("recipients", [])
        subject = draft.get("subject", "")
        email_content = draft.get("content", "")
        sent_count = 0
        sent_recipients = []
        try:
            for to_email in recipients:
                ok = send_email_direct(
                    to=to_email,
                    subject=subject,
                    content=email_content,
                    notification_type="report",       # 场景=经营报表（其他场景可传 risk_alert/reminder/催办）
                    trigger_source="email_dispatcher",  # 标记"系统调度器自动发"
                    triggered_by=user_id,             # 触发人：发起这次调度的用户 id
                )
                if "成功" in ok:
                    sent_count += 1
                    sent_recipients.append(to_email)

            return {
                "sent_count": sent_count,
                "recipients": sent_recipients,
                "subject": subject,
                "summary": f"邮件已发送至 {sent_count}/{len(recipients)} 位【{role}】",
            }
        except Exception as e:
            logger.error(f"EmailDispatcher 发送失败：{e}")
            return {
                "sent_count": sent_count,
                "recipients": sent_recipients,
                "subject": subject,
                "summary": f"邮件发送失败：{str(e)}",
            }

    # ---------- 私有辅助方法 ----------

    def _extract_emails(self, text: str) -> list[str]:
        """从 SQL 智能体返回的文本里解析邮箱列表"""
        import re
        emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        # 去重
        return list(set(emails))

    def _extract_subject(self, raw: str) -> tuple[str, str]:
        """首行「主题：X」→ (正文, X)；首行不是 → (原文, "")"""
        lines = (raw or "").splitlines()
        first = lines[0].strip() if lines else ""
        if first.startswith(("主题：", "主题:")):
            return "\n".join(lines[1:]).lstrip("\n"), first[3:].strip()
        return raw or "", ""
