# 图的状态（State + Reducer，含 clarify/system 等扩展字段）
# State = 图里跑的"数据包"模板：节点收 state 读数据、return dict 写数据（键名要对上）
# 字段注释统一格式：用途（谁写 → 谁读）
# Annotated[list, append_history] = Reducer 累加器：同名字段多次写入时累加不覆盖
# ====== history 永久存储（不截断，靠外部机制防 checkpointer 无限涨）======
# history 字段：完整对话历史，只追加不截断，永久保留供后续追问溯源
from typing import Annotated, TypedDict


def append_history(existing: list, new: list) -> list:
    """history 的 Reducer：只追加不截断，完整保留原文供后续追问溯源"""
    return (existing or []) + (new or [])


class State(TypedDict):
    """问题进来，资料查出来，回答出来"""
    question: str                       # 用户原始问题（/chat 入口写，全程不动 → 所有节点读）
    route: str                          # 分支结论（route 写 → build.py 条件边读）
    context: str                        # 查到的资料（rag/db/chart/system 写 → writer/chat 读）
    chart_json: dict                    # 图表 JSON（chart 写、route 每轮先清空 → chat_router 推 chart 帧）
    answer: str                         # 最终回答（writer/chat/clarify/system_send[取消时] 写 → chat_router 读）
    history: Annotated[list, append_history]   # 对话历史（writer/chat/clarify 各写一段，Reducer 累加不截断 → summarize/route/writer/chat 读）
    need_clarify: bool                  # 是否走了反问分支（route 写 → chat_router 读，推 clarify 帧）
    # route 入口改写（query rewriting）产出的自包含问题（润色后问题）。
    # 原始 question 不动——history 里记的还是用户视角的原文。
    rewritten_q: str                    # （route 写 → rag/db/chart/writer/chat 拿它代替原始 question）
    compressed_summary: str             # 历史块摘要拼接（summarize 写 → route/writer/chat 经 build_history_text 读）
    summary_upto: int = 0               # 摘要压到了第几轮（summarize 写 → summarize 自己读，决定下一块切点）
    memory_facts: list = []             # 关键事实清单（summarize 合并写 → route/writer/chat 经组装读；同 key 覆盖）
    system_result: dict = {}            # 发邮件调度结果（route 预填收件人 role → system_draft 读；system_send 写发送结果 → chat_router 推 system 帧、条件边读 cancelled 标志）
    # HITL 草稿必须放 state 而不是节点局部变量——interrupt 恢复后节点从头重跑，
    # 只有 checkpointer 里的 state 能跨断点存活。
    email_draft: dict = {}              # 待确认邮件草稿（system_draft 写 → system_send 读）
    user_id: int = 0                    # 当前用户 ID（/chat 入口写入 → system_send 读，写 notification_record.triggered_by）
