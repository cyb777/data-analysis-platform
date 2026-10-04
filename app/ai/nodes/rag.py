"""rag 节点：问指标口径时，去知识库检索相关定义，写进 context

物理位置：app/ai/nodes/（和 graph/ 平级）

RAG 工具调用走 app.ai.tool.rag_tool（统一工具层）
"""
from loguru import logger

from app.ai.tool.rag_tool import retrieve_schema_rag_tool


def rag_node(state):
    """RAG 节点：调 RAG 工具检索相关表结构/口径，写进 context"""
    q = state["question"]
    # 检索要用 route 改写后的自包含问题——
    # 拿"详细一点"这种原始追问去向量库搜不到相关口径。
    q = state.get("rewritten_q") or q
    # 走工具层（RAG 工具内部处理兜底重试）
    context = retrieve_schema_rag_tool.func(q)
    logger.info("  → rag 节点拿到 {} 段口径资料", context.count("---"))
    return {"context": context}
