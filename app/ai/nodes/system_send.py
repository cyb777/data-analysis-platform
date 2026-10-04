"""system_send 节点：发邮件调度第二步——interrupt 挂起等用户确认后发送

开头 interrupt() 挂起等用户点「确定发送」；
确认 → EmailDispatcher.send() 群发 + 落 notification_record → writer 润色
取消 → 直接写 answer 直连 END（不走 writer）

注意：interrupt 恢复后整个节点从头重跑，草稿经 state.email_draft 跨断点传递。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from langgraph.types import interrupt
from loguru import logger

from app.ai.agent.registry import email_dispatcher


def system_send_node(state):
    """发送节点：interrupt 挂起等用户确认，确认后才真发（副作用动作的人工断点）"""
    draft = state.get("email_draft") or {}

    # 起草失败（无收件人/查数异常）→ 不挂确认，直接把失败原因交给 writer 告诉用户
    if draft.get("error"):
        result = {"sent_count": 0, "recipients": [], "subject": "", "summary": draft["error"]}
        return {"system_result": result, "context": _failure_context(draft["error"])}

    # HITL 断点：payload 会经 SSE confirm 帧推到前端渲染确认卡片。
    # 第一次执行到这里整个图挂起（状态由 checkpointer 保存）；
    # 用户点击后 /chat/resume 以 Command(resume={...}) 恢复，interrupt() 返回用户决策。
    decision = interrupt({
        "recipients": draft.get("recipients", []),
        "subject": draft.get("subject", ""),
        "content": draft.get("content", ""),
    })

    # 取消：自己写答案直连 END（build.py 条件边）
    if not (decision or {}).get("confirm"):
        answer = "已取消，没有发送任何邮件。"
        logger.info("  → system_send 节点：用户取消发送")
        return {
            "answer": answer,
            "history": [(state["question"], answer)],
            "system_result": {"sent_count": 0, "recipients": [], "subject": draft.get("subject", ""),
                              "summary": "用户取消了发送", "cancelled": True},
        }

    # 确认：真发 + 落留痕
    user_id = state.get("user_id") or 0
    logger.info(f"  → system_send 节点：HITL 决策=确认，群发邮件（{len(draft.get('recipients', []))} 人, user_id={user_id}）")
    result = email_dispatcher.send(draft, user_id=user_id)

    # context 格式化在本节点做（writer 对所有分支一视同仁）
    out = {"system_result": result}
    if result.get("summary"):
        out["context"] = (
            f"【系统调度结果】\n"
            f"- 邮件主题：{result.get('subject', '')}\n"
            f"- 发送数量：{result.get('sent_count', 0)}\n"
            f"- 收件人：{', '.join(result.get('recipients', [])) or '（无）'}\n"
            f"- 调度摘要：{result['summary']}\n\n"
            f"【任务】\n"
            f"基于以上系统调度结果，生成一段简洁、专业的回复告诉用户"
            f"（不要复述上面的字段，直接说'已发送X封邮件给Y，主题Z'即可）。"
        )
    return out


def _failure_context(err: str) -> str:
    """起草失败时拼给 writer 的 context"""
    return (
        f"【系统调度结果】\n邮件起草失败：{err}\n\n"
        f"【任务】\n把这个失败原因用简洁、专业的语言告诉用户，并提示可以检查收件人配置后重试。"
    )
