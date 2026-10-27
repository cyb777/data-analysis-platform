# 图的状态（State + Reducer，含 clarify/system 等扩展字段）
# State = 图里跑的"数据包"模板：节点收 state 读数据、return dict 写数据（键名要对上）
# 字段注释统一格式：用途（谁写 → 谁读）
# Annotated[list, append_history] = Reducer 累加器：同名字段多次写入时累加不覆盖
# history 有界化（延迟截断：已压块原文入库 mem_43，超 HISTORY_HARD_LIMIT 才删最老一块）
# =====================================================================================
# history 字段：未压尾部（热层）+ 已入库未删的备份窗口；注入 prompt 的热层切 history[summary_upto - history_deleted:]
from datetime import datetime
from typing import Annotated, TypedDict


def append_history(existing: list, new: list) -> list:
    """history 的 Reducer：常规追加（顺手打时间戳）；summarize 截断写（哨兵元组）时保留最近 keep 轮。
    哨兵 = ("__truncate__", keep:int)——keep 必须是 int 才算数：用户若真输入
    "__truncate__"，普通问答二元组 (问题, 回答str) 不会误触发截断。
    时间戳：问答二元组 (q, a) 追加时补成 (q, a, "YYYY-MM-dd HH:mm")——给模型看的时间坐标
    （切块/节奏/幂等键仍走轮次内部坐标，见 summary_upto/history_deleted）。
    """
    match new:
        case [("__truncate__", int(keep))]:
            if keep > 0:
                return (existing or [])[-keep:]   # 留最后 keep 条
            return []                              # keep=0：清空
        case _:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            return (existing or []) + [(q, a, ts) for q, a in (new or [])]  # 正常追加+打戳

def resolve_q(state) -> str:
    """本轮实际用的问题：route 改写后的自包含问题优先，没有则原始 question。
    db/chart/rag/writer/chat/system_draft 六个下游节点统一从这取——改写策略变更只动一处。
    """
    return state.get("rewritten_q") or state["question"]


# 图状态由入口部分写入 + 各节点增量合并，运行期任何键都可能缺席，节点一律 state.get()
# 兜底——total=False 如实反映这一事实（TypedDict 里写 `= 0` 只是类属性，不产生运行时默认）。
class State(TypedDict, total=False):
    """问题进来，资料查出来，回答出来"""

    # 基本流转
    # ========
    question: str                       # 用户原始问题（/chat 入口写，全程不动 → 所有节点读）
    route: str                          # 分支结论（route 写 → build.py 条件边读；越权拦截时写 "end" 直连 END）
    context: str                        # 查到的资料（rag/db/chart/system 写 → writer/chat 读）
    chart_json: dict                    # 图表 JSON（chart 写、route 每轮先清空 → chat_router 推 chart 帧）
    answer: str                         # 最终回答（writer/chat/clarify/system_send[取消时]/route[越权拦截] 写 → chat_router 读）
    # route 入口改写（query rewriting）产出的自包含问题（润色后问题）。
    # 原始 question 不动——history 里记的还是用户视角的原文。
    rewritten_q: str                    # （route 写 → rag/db/chart/writer/chat 拿它代替原始 question）
    user_id: int                        # 当前用户 ID（/chat 入口写入 → route 权限门判 system 登录态；system_send 读，写 notification_record.triggered_by）
    # 员工级别（1实习/见习 2正式 3经理 4老板 5管理员）：JWT 签发时带入，/chat 入口每轮刷新写入
    # → route 权限门（db/chart 要 >=3）、system_draft 读（邮件工具分级 + 收件人 +1 规则过滤）
    user_level: int

    # 三层记忆（热层 history / 温层 summary+facts / 冷层 mem_43）
    # ===========================================================
    history: Annotated[list, append_history]   # 对话历史-未压尾部+备份窗口（writer/chat/clarify 各写一段；summarize 超上限哨兵删最老一块，已压块原文在 mem_43 → summarize/route/writer/chat 读）
    # 注意：thread_id 不进 state——config["configurable"]["thread_id"] 本来就有，
    # 需要的节点（summarize/chat）经签名注入 config 拿。
    history_deleted: int                # 已累计哨兵删除的轮次（summarize 截断时累加 → 列表下标 = 全局轮次 - history_deleted；summary_upto 是全局轮次，严禁直接当列表下标）
    compressed_summary: str             # 历史块摘要拼接（summarize 写 → route/writer/chat 经 build_history_text 读）
    summary_upto: int                   # 摘要压到了第几轮（summarize 写 → summarize 自己读，决定下一块切点）
    memory_facts: list                  # 关键事实清单（summarize 合并写 → route/writer/chat 经组装读；同 key 覆盖）

    # 邮件调度（system 分支）
    # =======================
    system_result: dict                 # 发邮件调度结果（system_send 写发送结果 → chat_router 推 system 帧、条件边读 cancelled 标志；收件人提取归 dispatcher）
    # HITL 草稿必须放 state 而不是节点局部变量——interrupt 恢复后节点从头重跑，
    # 只有 checkpointer 里的 state 能跨断点存活。
    email_draft: dict                   # 待确认邮件草稿（system_draft 写 → system_send 读）


