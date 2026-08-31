"""数据分析智能体：基于前序节点的资料与对话历史，生成最终分析结论。

图表由 EchartsAgent 单独生成，本智能体只负责纯文本回答。
"""
from loguru import logger

from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import sql_query_tool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage


class AnalyzeAgent:
    def __init__(self):
        logger.info("初始化数据分析智能体")
        self.model = MyModel.get_model()
        self.tools = self.__init__tools()
        self.agent = self.__init__agent()

    def __init__tools(self):
        # 只读工具：资料不足时允许再查一次库，但不允许任何写操作
        self.tools = [sql_query_tool]
        return self.tools

    def __init__agent(self):
        prompt = """
        一:你是一个数据分析智能体,你有一个工具sql_query_tool
        二:工作流程:请严格按照以下步骤执行
        1.根据【相关资料】整理数据；资料不足时可调用sql_query_tool查询（只读，只允许select）
        2.根据问题做出详细的分析，按照以下格式分析:
            详细分析:
                1：xxxx
                2：xxxx
            结论分析:
                xxxx
        3.如果相关资料里有图表JSON，用一句话说明图表讲了什么（图表由图表智能体生成，你不需要再生成）
        三:重要规则
        1.sql查询规范
            - 只能使用select查询，不能delete操作
        2.查询原则
            - 当涉及到排名top时，必须用order by 和limit 
            - 多表查询时，必须使用join 
            - 只查询前5条数据
        3.资料里没有的就直说不知道，不要编造；数据问题先给结论，再给关键数字
        """
        # 不设 response_format：纯文本输出，便于流式推送
        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
        )
        return agent

    def answer(self, question: str, context: str, history_text: str) -> str:
        """综合分析并生成最终回答

        :param question: 用户问题
        :param context: 前序节点（RAG/数据库/图表）产出的资料
        :param history_text: 对话历史，由图的 Checkpoint 维护
        """
        try:
            response = self.agent.invoke(
                {"messages": [HumanMessage(content=(
                    f"【相关资料】\n{context}\n\n"
                    f"【对话历史】\n{history_text}\n\n"
                    f"【用户问题】\n{question}"
                ))]},
            )
            data = str(response["messages"][-1].content)
            logger.info("回答完成：{} 字", len(data))
            return data
        except Exception as e:
            logger.error(e)
            return str(e)


if __name__ == '__main__':
    agent = AnalyzeAgent()
    print(agent.answer("销售额是多少", "查询结果：手机 50000，电脑 30000", "（暂无）"))
