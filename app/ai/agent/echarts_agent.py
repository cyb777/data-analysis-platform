# EchartsAgent ECharts图表智能体：只读查库 + 生成 ChartData 结构化图表 JSON。
# answer 收 metric_text（RAG 检索的指标口径/查询规范）；骨架在 BaseToolAgent，重试走 invoke_with_structured_retry。
from loguru import logger

from app.ai.agent.registry import BaseToolAgent, invoke_with_structured_retry
from app.ai.tool.mysql_tool import sql_query_tool, describe_table_tool
from app.ai.schemas.llm_chart_schema import ChartData


class EchartsAgent(BaseToolAgent):
    # 工具列表：sql_query_tool 只读护栏 + describe_table_tool 自查列名
    tools = [sql_query_tool, describe_table_tool]

    # 提示词保持精简：防瞎编靠 describe_table 自查 + response_format 强约束，不靠 prompt 喊话
    system_prompt = """
    一:你是一个ECharts图表智能体,你有两个工具:sql_query_tool（只读查询）、describe_table（查表结构）
    二:工作流程:请严格按照以下步骤执行
        1.如果用户提问图表生成，请先根据消息里的【指标口径与查询规范】查询数据库，生成一个echarts图表
        2.列名不确定时，先用 describe_table 查实际列名再写 SQL
        3.返回的图表需要是前端可直接渲染的 JSON（结构化输出见 response_format）
    三:重要规则
    1.sql查询规范
        - 只能使用select查询，不能delete操作
        - 涉及"总共/一共"用SUM()；日期字段为 DATE/DATETIME，按时间区间过滤
        - GROUP BY 严格匹配 SELECT 非聚合列（MySQL 5.7+ only_full_group_by）
        - 资料里的 SQL 模板仅做参考：口径（公式/过滤条件）必须遵守，SQL 文本按实际问题改写
    2.查询原则
        - 当涉及到排名top时，必须用order by 和limit
        - 多表查询时，必须使用join
        - 只查询前5条数据
        - 时间口径：用户问题没指定时间范围时，默认按最近30天统计，并在图表标题里注明；
          问题已含时间（本月、2024年、最近7天等）以问题为准；TOP N/最高最低按全时段排名
    3.图表结构（ChartData）：x_axis放类别/时间等维度，series放对应的数值，两者数量一致；chart_type只允许bar/line/pie
    """

    # response_format：最后必须输出 ChartData 结构（图表JSON），不符合就让它重写，
    # 结果放在 structured_response 键里
    response_format = ChartData

    def answer(self, question: str, metric_text: str):
        """收用户问题 + RAG 口径/规范资料，返回 ChartData dict；3 次失败返回兜底占位图"""
        content = f"{metric_text}\n\n【用户问题】{question}"
        structured, err = invoke_with_structured_retry(self.agent, content, label="EchartsAgent")
        if structured is None:
            # 3 次都失败：返回兜底 ChartData + 原因，前端渲染"无数据"占位 + toast 提示
            err_msg = str(err) if err else "未知原因"
            logger.error("图表生成最终失败（{}），返回兜底 ChartData", err_msg)
            return {
                "title": f"（图表生成失败）{question[:30]}",
                "chart_type": "bar",
                "x_axis": ["暂无数据"],
                "series": [0],
                "fallback_reason": err_msg[:200],  # 前端 toast 提示用
            }
        # structured_response 是按 response_format 规范好的结构化数据；
        # .model_dump() 把 Pydantic 对象转成普通 dict（JSON 友好）
        data = structured.model_dump()
        logger.info("EchartsAgent 已生成 ChartData：{}", data)
        return data


if __name__ == '__main__':
    agent = EchartsAgent()
    print(agent.answer("画个最近6个月各酒店 RevPAR 趋势折线图", "stay_record 表：stay_id, hotel_id, actual_check_in, nights, room_amount"))
