"""chart 节点：EchartsAgent 查库 + 生成 ECharts JSON

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from loguru import logger

from app.ai.rag.retriever import build_metric_block
from app.ai.agent.registry import echarts_agent
from app.ai.graph.state import resolve_q


def chart_node(state):
    """图表节点（EchartsAgent）：RAG 检索资料 → 智能体查库 + 生成 ECharts JSON"""
    # 检索和查库都用 route 改写后的自包含问题（resolve_q 统一收口）——
    # 注意顺序：必须先替换再检索，拿"详细一点"三个字去向量库搜不到相关表结构。
    q = resolve_q(state)
    metric_block = build_metric_block(q)   # 口径/规范资料块（表列全量字典在 sql_query 工具说明）
    chart_json = echarts_agent.answer(q, metric_block)

    if chart_json:
        return {
            "context": (
                f"用户问题:{q}\n"
                f"相关业务口径:\n{metric_block}\n"
                f"图表JSON:\n{chart_json}\n"
                # 反向指令：不罗列表名/SQL/渲染细节
                f"（图表已自动渲染给用户，你只需用一句话说明图表讲了什么；"
                f"不要罗列查了哪些表、用了什么 SQL、图表由谁渲染）"
            ),
            "chart_json": chart_json,
        }
    logger.warning("  → chart 节点：图表生成失败，本次只返回文字分析")
    return {
        "context": f"用户问题:{q}\n相关业务口径:\n{metric_block}\n（图表生成失败，请在文字里说明数据情况）",
    }
