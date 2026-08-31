"""ECharts图表智能体：查询数据库并生成 ECharts 图表 JSON。"""
from loguru import logger

from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import sql_query_tool
from app.ai.schema.chart_schema import ChartData
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage


class EchartsAgent:
    def __init__(self):
        logger.info("初始化ECharts图表智能体")
        self.model = MyModel.get_model()
        self.tools = self.__init__tools()
        self.agent = self.__init__agent()

    def __init__tools(self):
        self.tools = [sql_query_tool]
        return self.tools

    def __init__agent(self):
        prompt = """
        一:你是一个ECharts图表智能体,你有一个工具sql_query_tool
        二:工作流程:请严格按照以下步骤执行
        1.如果用户提问图表生成，请先根据消息里的【表结构资料】查询数据库，生成一个echarts图表
        2.返回的数据必须是一个可执行的json格式，其他文本信息不重要（结构化输出见response_format）
        3.返回的图表需要具有保存功能
        三:重要规则
        1.sql查询规范
            - 只能使用select查询，不能delete操作
            - 涉及"总共/一共"用SUM()；日期是text类型直接比字符串；金额只算已完成订单（order_status='已完成'）
        2.查询原则
            - 当涉及到排名top时，必须用order by 和limit 
            - 多表查询时，必须使用join 
            - 只查询前5条数据
        3.图表结构（ChartData）：x_axis放类别/时间等维度，series放对应的数值，两者数量一致；chart_type只允许bar/line/pie
        """
        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
            response_format=ChartData,   # 约束输出为 ChartData 结构，保证前端能直接渲染
        )
        return agent

    def answer(self, question: str, schema_text: str):
        """查询数据并生成图表 JSON

        :param question: 用户问题
        :param schema_text: RAG 检索出的相关表结构
        """
        try:
            response = self.agent.invoke(
                {"messages": [HumanMessage(content=f"【表结构资料】\n{schema_text}\n\n【用户问题】{question}")]},
            )
            data = response["structured_response"].model_dump()

            logger.info("用户回答问题:{}", data)
            return data
        except Exception as e:
            logger.error(e)
            return e


if __name__ == '__main__':
    agent = EchartsAgent()
    print(agent.answer("画个各产品类别的销售额柱状图", "sales 表：year, total_sales, category"))
