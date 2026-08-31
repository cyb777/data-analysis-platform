"""SQL 问题智能体：将自然语言转换为 SQL，查询数据库并返回结果资料。

只负责取数，不做结论分析（分析由 AnalyzeAgent 完成）。
"""
from loguru import logger

from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import sql_query_tool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage


class SQLQuestionAgent:
    def __init__(self):
        logger.info("SQLQuestionAgent初始化")
        self.model = MyModel.get_model()
        self.tools = self.__init__tools()
        self.agent = self.__init__agent()

    def __init__tools(self):
        self.tools = [sql_query_tool]
        return self.tools

    def __init__agent(self):
        prompt = """
        一:你是一个sql问题智能体,你有一个工具sql_query_tool
        二:重要规则：
            只能进行select查询，不能进行delete 操作
        三：使用规则：
            1.如果查询销售数据查询，请查询sales
            2.多表查询，请使用join
            3.不要回答你的思考过程
        四:补充规则（表结构以消息里的【表结构资料】为准）:
            1.涉及"总共/一共"用SUM()
            2.日期是text类型直接比字符串
            3.金额只算已完成订单（order_status='已完成'）
            4.调用工具查库后，把查询结果原样整理成资料文本返回，不要写总结和结论（那是分析智能体的活）
        """
        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
        )
        return agent

    def answer(self, question: str, schema_text: str) -> str:
        """执行查询并返回结果资料文本

        :param question: 用户问题
        :param schema_text: RAG 检索出的相关表结构
        """
        rs = self.agent.invoke({
            "messages": [HumanMessage(content=f"【表结构资料】\n{schema_text}\n\n【用户问题】{question}")]
        })
        # 智能体可能多轮查库，取最后一次工具执行结果
        for m in reversed(rs["messages"]):
            if getattr(m, "type", "") == "tool":
                result = str(m.content)
                logger.info("查询完成：{} 字", len(result))
                return result
        return str(rs["messages"][-1].content)


if __name__ == '__main__':
    agent = SQLQuestionAgent()
    print(agent.answer("各产品类别的销售额", "sales 表：year, total_sales, total_orders, category"))
