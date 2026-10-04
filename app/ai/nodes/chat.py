"""chat 节点：对话式追问的轻量回答

route 直派的对话式追问（"详细分析""具体怎么做？"）走这里：
单次模型调用，无工具、无 ReAct 循环，直连 END。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.ai.graph.context_compressor import node_history_text
from app.ai.model.model import MyModel

# 最小提示词：只留三条底线——身份、不编造、问什么答什么
_CHAT_PROMPT = (
    "你是连锁酒店管理助手的对话助手，正在和酒店管理人员进行多轮对话。"
    "基于【对话历史】和【已有资料】用自然的对话口吻直接回答。"
    "历史里没有的数据不要编造；用户问什么就答什么，不要套用固定报告结构。"
)


def chat_node(state):
    """对话节点：route 直派的追问/闲聊，单次模型调用直接回答"""
    # 用 route 改写后的自包含问题回答；
    # history 里记的是用户的原始问法，保持对话历史的自然形态（与 writer 节点同一约定）。
    question = state.get("rewritten_q") or state["question"]
    # checkpointer 会恢复上一轮的 context（上次取数结果），追问数据时正好用上
    context = state.get("context", "")
    # 三层记忆统一组装（与 route/writer 同一入口）
    history_text = node_history_text(state)

    answer = str(MyModel.get_model().invoke([
        SystemMessage(content=_CHAT_PROMPT),
        HumanMessage(content=(
            f"【已有资料】\n{context or '（无）'}\n\n"
            f"【对话历史】\n{history_text}\n\n"
            f"【用户问题】\n{question}"
        )),
    ]).content)
    logger.info("chat 节点对话回答完成：{} 字", len(answer))
    # 把这轮"问+答"追加进 history，Reducer 自动累加而不是覆盖
    return {"answer": answer, "history": [(state["question"], answer)]}
