"""system_draft 节点：发邮件调度第一步——起草邮件（不发送）

EmailDispatcher.prepare()：查数据 → 查收件人 → 写正文，草稿进 state.email_draft。
下一步是 system_send 节点（interrupt 挂起等用户确认）。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from loguru import logger

from app.ai.agent.registry import email_dispatcher


def system_draft_node(state):
    """起草节点：查数 → 查收件人 → 写正文 → 草稿写进 state.email_draft（不发送）"""
    # 用改写后的自包含问题（多轮追问时，原始 question 可能只是"再发一份"，rewritten_q 才是完整问题）
    question = state.get("rewritten_q") or state["question"]
    sys_meta = state.get("system_result") or {}
    recipient_role = sys_meta.get("recipient_role") or "分公司老板"

    logger.info(f"  → system_draft 节点：起草邮件（role={recipient_role}）")
    draft = email_dispatcher.prepare(question=question, recipient_role=recipient_role)
    return {"email_draft": draft}
