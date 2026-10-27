"""chat 节点：对话式追问 / 闲聊 + 冷层历史回查的唯一责任方

route 直派的对话式追问（"详细分析""具体怎么做？""我之前留的邮箱是啥"）走这里：
单次模型调用，无工具、无 ReAct 循环，直连 END。

冷层回查只在 chat 做：追问/指代/溯源类问题归 chat 承接，回查成本只发生在这一条分支；
其余节点（route/writer/clarify）只调 node_history_text 拼热层+温层、不碰向量库
——它们靠温层 memory_facts（邮箱/口径/收件人等常驻事实）+ 摘要 + 热层尾部就够。
这里单独调 recall_text 拿到【原文回查】段后自行拼接。

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.ai.graph.state import resolve_q
from app.ai.mem.recall import node_history_text, recall_text
from app.ai.model.model import MyModel

# 最小提示词：只留三条底线——身份、不编造、问什么答什么
_CHAT_PROMPT = (
    "你是连锁酒店管理助手的对话助手，正在和酒店管理人员进行多轮对话。"
    "基于【对话历史】和【已有资料】用自然的对话口吻直接回答。"
    "历史里没有的数据不要编造；用户问什么就答什么，不要套用固定报告结构。"
)


def chat_node(state, config=None):
    """对话节点：route 直派的追问/闲聊，单次模型调用直接回答。
    config 由 LangGraph 注入——冷层回查要从这里拿 thread_id（不进 state）。"""
    # 用 route 改写后的自包含问题回答（resolve_q 统一收口）；
    # history 里记的是用户的原始问法，保持对话历史的自然形态（与 writer 节点同一约定）。
    question = resolve_q(state)
    # checkpointer 会恢复上一轮的 context（上次取数结果），追问数据时正好用上
    context = state.get("context", "")
    # 三层记忆：热层+温层由 node_history_text 拼；冷层回查单独调 recall_text（本节点是唯一回查方）
    history_text = node_history_text(state)
    recall = recall_text(state, config)
    if recall:
        history_text = f"{history_text}\n\n{recall}"

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
