"""db 节点：RAG 检索口径资料 → 智能体写 SQL 查库 → 结果写进 context
对比分析场景由 chart 节点出对比图覆盖（v1.5.6 之后：db 节点回归纯查询，不背对比专属逻辑）

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from app.ai.rag.retriever import build_metric_block
from app.ai.agent.registry import sql_agent
from app.ai.graph.state import resolve_q


def db_node(state):
    """数据库节点（SQLQuestionAgent）：RAG 检索口径资料 → 智能体写 SQL 查库 → 结果写进 context
    表列全量字典在 sql_query 工具说明里；检索只背口径/规范（缺字段让 LLM 用 describe_table 自查）
    """
    # 检索和查库都用 route 改写后的自包含问题（resolve_q 统一收口）——
    # 注意顺序：必须先替换再检索，拿"详细一点"三个字去向量库搜不到相关表结构。
    q = resolve_q(state)
    metric_block = build_metric_block(q)   # 口径/规范资料块（表列字典在 sql_query 工具说明，不重复抽列名）
    result = sql_agent.answer(q, metric_block)
    return {
        "context": (
            f"用户问题:{q}\n"
            f"相关业务口径:\n{metric_block}\n"
            f"数据库查询结果:\n{result}\n"
            # 反向指令：回答里不罗列查了哪些表、用了什么 SQL
            f"（以上资料仅供你分析使用，回答里不要罗列查了哪些表、用了什么 SQL）"
        ),
    }
