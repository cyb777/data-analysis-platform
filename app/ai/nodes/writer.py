"""writer 节点：AnlyzeAgent 综合分析资料 + 对话历史，生成最终回答

上游只接 rag/db/chart 分析类分支（资料在各自节点写进 context）；
system 分支的操作结果通知是模板话，在 system_send 节点内自写 answer 直连 END，不经本节点。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from app.ai.agent.registry import anlyze_agent
from app.ai.graph.state import resolve_q
from app.ai.mem.recall import node_history_text   # 三层记忆组装（事实/摘要/热层）收敛到公共层


def writer_node(state):
    """写作节点（AnlyzeAgent）：综合分析资料 + 对话历史，生成最终回答"""
    # 用 route 改写后的自包含问题（润色后问题）回答——
    # 与 db/chart/rag/chat 同款约定（resolve_q 统一收口），让所有下游节点都吃同一份上下文处理结果。
    question = resolve_q(state)
    context = state.get("context", "")
    # 热层+温层：关键事实 + 块摘要 + 未压原文带轮次编号。不做冷层回查（只在 chat 做）：
    # 本节点吃前序查好的当前资料，注入旧轮原文会让模型把旧数字当本轮数据用
    history_text = node_history_text(state)

    answer = anlyze_agent.answer(question, context, history_text)
    # 把这轮"问+答"追加进 history，Reducer 自动累加而不是覆盖
    # history 统一记用户原文 question（和 chat/clarify/system_send 口径一致），
    # rewritten_q 只用于本轮取数/作答，不进历史，避免多轮后语义漂移。
    return {"answer": answer, "history": [(state["question"], answer)]}
