# EchartsAgent ECharts图表智能体：只读查库 + 生成 ChartData 结构化图表 JSON。
# answer 收 schema_text（RAG 检索的表结构资料）；agent 提前到 __init__ 建一次（图节点反复调用）。
from loguru import logger
from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import sql_query_tool, describe_table_tool
from app.ai.schemas.llm_chart_schema import ChartData
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage


class EchartsAgent:
    def __init__(self):
        logger.info("初始化ECharts图表智能体")
        self.model = MyModel.get_model()
        self.tools = self.__init__tools()
        # 记忆由图管，不重复设
        self.agent = self.__init__agent()

    #私有方法
    def __init__tools(self):
       # 工具列表：sql_query_tool 只读护栏 + describe_table_tool 自查列名
       self.tools = [sql_query_tool, describe_table_tool]
       return self.tools

    def __init__agent(self):
        # 提示词保持精简：防瞎编靠 describe_table 自查 + response_format 强约束，不靠 prompt 喊话
        prompt = """
        一:你是一个ECharts图表智能体,你有两个工具:sql_query_tool（只读查询）、describe_table（查表结构）
        二:工作流程:请严格按照以下步骤执行
            1.如果用户提问图表生成，请先根据消息里的【表结构资料】查询数据库，生成一个echarts图表
            2.列名不确定时，先用 describe_table 查实际列名再写 SQL
            3.返回的图表需要是前端可直接渲染的 JSON（结构化输出见 response_format）
        三:重要规则
        1.sql查询规范
            - 只能使用select查询，不能delete操作
            - 涉及"总共/一共"用SUM()；日期字段为 DATE/DATETIME，按时间区间过滤
            - GROUP BY 严格匹配 SELECT 非聚合列（MySQL 5.7+ only_full_group_by）
        2.查询原则
            - 当涉及到排名top时，必须用order by 和limit
            - 多表查询时，必须使用join
            - 只查询前5条数据
            - 时间口径：用户问题没指定时间范围时，默认按最近30天统计，并在图表标题里注明；
              问题已含时间（本月、2024年、最近7天等）以问题为准；TOP N/最高最低按全时段排名
        3.图表结构（ChartData）：x_axis放类别/时间等维度，series放对应的数值，两者数量一致；chart_type只允许bar/line/pie
        """
        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
            # response_format：最后必须输出 ChartData 结构（图表JSON），不符合就让它重写，
            # 把结果放在 structured_response 键里
            response_format=ChartData,
        )
        return agent

    def answer(self, question: str, schema_text: str):
        """收用户问题 + RAG 表结构资料，返回 ChartData dict；3 次失败返回兜底占位图"""
        # 重试机制：模型偶发"不调结构化工具、直接输出纯文本"（此时返回里
        # 没有 structured_response 键，直接取会 KeyError），重试几次通常就正常
        last_err = None
        for attempt in range(1, 4):
            try:
                #调用智能体回答问题
                response = self.agent.invoke(
                    {"messages": [HumanMessage(content=f"【表结构资料】\n{schema_text}\n\n【用户问题】{question}")]},
                )
                # 防御性取键：response.get() 拿不到返回 None，不像 [] 直接抛 KeyError
                structured = response.get("structured_response")
                if structured is None:
                    last_err = "模型本次未按 ChartData 结构化格式输出（structured_response 缺失）"
                    logger.warning("第{}次未拿到结构化图表，重试", attempt)
                    continue
                # structured_response 是按 response_format 规范好的结构化数据；
                # .model_dump() 把 Pydantic 对象转成普通 dict（JSON 友好）
                data = structured.model_dump()

                logger.info("EchartsAgent 已生成 ChartData：{}", data)
                return data
            except Exception as e:
                last_err = e
                logger.warning("第{}次生成图表出错：{}，重试", attempt, e)
        # 3 次都失败：返回兜底 ChartData + 原因，前端渲染"无数据"占位 + toast 提示
        err_msg = str(last_err) if last_err else "未知原因"
        logger.error("图表生成最终失败（{}），返回兜底 ChartData", err_msg)
        return {
            "title": f"（图表生成失败）{question[:30]}",
            "chart_type": "bar",
            "x_axis": ["暂无数据"],
            "series": [0],
            "fallback_reason": err_msg[:200],  # 前端 toast 提示用
        }


if __name__ == '__main__':
    agent = EchartsAgent()
    print(agent.answer("画个最近6个月各酒店 RevPAR 趋势折线图", "stay_record 表：stay_id, hotel_id, actual_check_in, nights, room_amount"))
