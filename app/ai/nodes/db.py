"""db 节点：RAG 检索表结构 + 提取列名白名单 → 智能体写 SQL 查库 → 结果写进 context
对比分析场景由 chart 节点出对比图覆盖（v1.5.6 之后：db 节点回归纯查询，不背对比专属逻辑）

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from app.ai.tool.rag_tool import build_schema_block
from app.ai.agent.registry import sql_agent


def db_node(state):
    """数据库节点（SQLQuestionAgent）：RAG 检索表结构 → 智能体写 SQL 查库 → 结果写进 context
    RAG 不光给资料，还解析出本次召回到的列名清单（缺表让 LLM 用 describe_table 自查）
    """
    q = state["question"]
    # route 已把多轮追问结合历史改写成了自包含问题，检索和查库都用改写后的。
    # 注意顺序：必须先替换再检索——拿"详细一点"三个字去向量库搜不到相关表结构。
    q = state.get("rewritten_q") or q
    schema, schema_with_whitelist = build_schema_block(q)
    result = sql_agent.answer(q, schema_with_whitelist)
    return {
        "context": (
            f"用户问题:{q}\n"
            f"涉及的表结构:\n{schema_with_whitelist}\n"
            f"数据库查询结果:\n{result}\n"
            # 反向指令：回答里不罗列查了哪些表、用了什么 SQL
            f"（以上资料仅供你分析使用，回答里不要罗列查了哪些表、用了什么 SQL）"
        ),
    }
