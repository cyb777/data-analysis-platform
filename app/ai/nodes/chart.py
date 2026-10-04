"""chart 节点：EchartsAgent 查库 + 生成 ECharts JSON

物理位置：app/ai/nodes/（和 graph/ 平级）
"""
from loguru import logger

from app.ai.tool.rag_tool import build_schema_block
from app.ai.agent.registry import echarts_agent


def chart_node(state):
    """图表节点（EchartsAgent）：RAG 检索资料 → 智能体查库 + 生成 ECharts JSON"""
    q = state["question"]
    # route 已把多轮追问结合历史改写成了自包含问题，检索和查库都用改写后的。
    # 注意顺序：必须先替换再检索——拿"详细一点"三个字去向量库搜不到相关表结构。
    q = state.get("rewritten_q") or q
    schema, schema_with_whitelist = build_schema_block(q)
    chart_json = echarts_agent.answer(q, schema_with_whitelist)

    if chart_json:
        return {
            "context": (
                f"用户问题:{q}\n"
                f"涉及的表结构:\n{schema_with_whitelist}\n"
                f"图表JSON:\n{chart_json}\n"
                # 反向指令：不罗列表名/SQL/渲染细节
                f"（图表已自动渲染给用户，你只需用一句话说明图表讲了什么；"
                f"不要罗列查了哪些表、用了什么 SQL、图表由谁渲染）"
            ),
            "chart_json": chart_json,
        }
    logger.warning("  → chart 节点：图表生成失败，本次只返回文字分析")
    return {
        "context": f"用户问题:{q}\n涉及的表结构:\n{schema}\n（图表生成失败，请在文字里说明数据情况）",
    }
