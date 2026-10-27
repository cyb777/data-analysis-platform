"""system_draft 节点：发邮件调度第一步——起草邮件（不发送）

EmailDispatcher.prepare()：写作 agent 自主成稿（直查 SQL + 分析/检索，
结构化输出自带收件人）→ 查邮箱（起草即校验），草稿进 state.email_draft。
下一步是 system_send 节点（interrupt 挂起等用户确认）。
发信权限在 route 节点统一收口（system 分支要经理级 level>=3），本节点只附发起人署名。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from loguru import logger

from app.ai.agent.registry import email_dispatcher
from app.ai.graph.state import resolve_q
from app.ai.tool.mysql_tool import query_one
from app.ai.mem.recall import node_history_text


def system_draft_node(state):
    """起草节点：写作 agent 成稿+校验 → 附发起人署名 → 草稿进 state（不发送）"""
    # 用改写后的自包含问题（resolve_q 统一收口；多轮追问时原始 question 可能只是"再发一份"，rewritten_q 才是完整问题）；
    # 对话上下文一并交给 dispatcher——收件人指代还原、正文素材（"把刚才讨论的发出去"）都可能用它
    question = resolve_q(state)
    history_text = node_history_text(state)

    # 发信权限在 route 收口（level>=3），本节点不再向 prepare 传级别参数——dispatcher 只查邮箱
    logger.info("  → system_draft 节点：起草邮件")
    draft = email_dispatcher.prepare(question=question, history_text=history_text)
    # 发起人署名：收件人能看到这封系统邮件是谁触发的（可追溯、防滥用；确认卡片同步可见）。
    # 不做匿名/查无此人兜底：route 门已拦 level<3（匿名 user_level=0 含在内），能到本节点则 employee 行必在。
    if not draft.get("error"):
        row = query_one(
            "SELECT employee_name, position FROM employee WHERE employee_id=%s",
            (state.get("user_id"),))
        draft["content"] = (draft.get("content") or "") + \
            f"\n\n——本邮件由 {row[0] or ''}（{row[1] or ''}）经酒店管理系统发起"
    return {"email_draft": draft}
