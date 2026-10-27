"""rag 节点：问指标口径时，去知识库检索相关定义，写进 context

物理位置：app/ai/nodes/（和 graph/ 平级）

RAG 检索走 app.ai.rag.retriever（在线检索层；建库管线在 app.ai.rag.builder）
"""
from loguru import logger

from app.ai.rag import retriever
from app.ai.graph.state import resolve_q


def rag_node(state):
    """RAG 节点：检索相关表结构/口径，写进 context"""
    # 检索要用 route 改写后的自包含问题（resolve_q 统一收口）——
    # 拿"详细一点"这种原始追问去向量库搜不到相关口径。
    q = resolve_q(state)
    # 只召回 tag=hotel 的业务口径定义段，不被表结构段污染
    context = retriever.retrieve_schema(q, tag_filter="hotel")
    logger.info("  → rag 节点拿到 {} 段口径资料", context.count("---"))
    return {"context": context}
