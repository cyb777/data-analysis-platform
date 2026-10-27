"""system_send 节点：发邮件调度第二步——interrupt 挂起等用户确认后发送

开头 interrupt() 挂起等用户点「确定发送」；
确认 → EmailDispatcher.send() 群发 + 落 notification_record
取消 / 起草失败 → 不发送

三分支都在节点内自写 answer 直连 END：system 的操作结果通知是模板话
（摘要/拦截话术起草时已定），走 writer 让 LLM 复述一遍只会白等一轮调用。
writer 只服务 db/chart/rag 分析类分支。

注意：interrupt 恢复后整个节点从头重跑，草稿经 state.email_draft 跨断点传递。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from langgraph.types import interrupt
from loguru import logger

from app.ai.agent.registry import email_dispatcher


def _done(state, answer: str, system_result: dict) -> dict:
    """三个出口统一收口：自写 answer + history（与 writer 口径一致，记用户原文），
    附 system_result 供前端渲染结果卡片"""
    return {
        "answer": answer,
        "history": [(state["question"], answer)],
        "system_result": system_result,
    }


def system_send_node(state):
    """发送节点：interrupt 挂起等用户确认，确认后才真发（副作用动作的人工断点）"""
    draft = state.get("email_draft") or {}

    # 起草失败（查无此人/越权/未绑邮箱/模型异常）→ 不挂确认，事实话术直接答
    if draft.get("error"):
        logger.info(f"  → system_send 节点：起草失败，{draft['error']}")
        return _done(state, draft["error"], {
            "sent_count": 0, "recipients": [], "subject": "",
            "summary": draft["error"],
            "failed": True,   # 前端按此渲染灰色"起草失败"卡（缺省会误显示成绿色"已发送"卡）
        })

    # HITL 断点：payload 会经 SSE confirm 帧推到前端渲染确认卡片。
    # 第一次执行到这里整个图挂起（状态由 checkpointer 保存）；
    # 用户点击后 /chat/resume 以 Command(resume={...}) 恢复，interrupt() 返回用户决策。
    decision = interrupt({
        "recipients": draft.get("recipients", []),
        "subject": draft.get("subject", ""),
        "content": draft.get("content", ""),
        "no_email": draft.get("no_email", []),   # 未绑邮箱名单：确认卡片提醒"这些人收不到"
        "external": draft.get("external", []),   # @ 直放未校验地址：确认卡片黄色提醒核对
    })

    # 取消
    if not (decision or {}).get("confirm"):
        logger.info("  → system_send 节点：用户取消发送")
        return _done(state, "已取消，没有发送任何邮件。", {
            "sent_count": 0, "recipients": [], "subject": draft.get("subject", ""),
            "summary": "用户取消了发送", "cancelled": True,
        })

    # 确认：直接群发草稿确认集（校验在 prepare 起草时已完成，所见即所发）+ 落留痕
    user_id = state.get("user_id") or 0
    logger.info(f"  → system_send 节点：HITL 决策=确认，群发（user_id={user_id}）")
    result = email_dispatcher.send(draft, user_id=user_id)
    # summary 已是人话（"邮件已发送至 X/Y 位收件人（职位）"），补上主题就是最终答复
    return _done(state, f"{result['summary']}，主题《{result['subject']}》", result)
