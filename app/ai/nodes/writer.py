"""writer 节点：AnlyzeAgent 综合分析资料 + 对话历史，生成最终回答

system 场景的 context 在 system 节点格式化，本节点对所有上游分支一视同仁。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from app.ai.agent.registry import anlyze_agent
from app.ai.graph.context_compressor import node_history_text   # 三层记忆组装（事实/摘要/热层+回查）收敛到公共层


def writer_node(state):
    """写作节点（AnlyzeAgent）：综合分析资料 + 对话历史，生成最终回答"""
    # 用 route 改写后的自包含问题（润色后问题）回答——
    # 与 db/chart/rag/chat 同款约定，让所有下游节点都吃同一份上下文处理结果。
    question = state.get("rewritten_q") or state["question"]
    context = state.get("context", "")
    # 三层记忆统一组装：关键事实 + 块摘要 + 未压块原文（溯源问题自动回查冷层）
    history_text = node_history_text(state)

    answer = anlyze_agent.answer(question, context, history_text)
    # 把这轮"问+答"追加进 history，Reducer 自动累加而不是覆盖
    # history 统一记用户原文 question（和 chat/clarify/system_send 口径一致），
    # rewritten_q 只用于本轮取数/作答，不进历史，避免多轮后语义漂移。
    return {"answer": answer, "history": [(state["question"], answer)]}
