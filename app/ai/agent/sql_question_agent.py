# SQLQuestionAgent SQL问题智能体：只读查库，把查询结果整理成"列名+数值"的资料文本。
# answer 收 schema_text（RAG 检索的表结构资料），智能体只看相关表。
from loguru import logger
from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import sql_query_tool, describe_table_tool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage


class SQLQuestionAgent:
    def __init__(self):
        logger.info("SQLQuestionAgent初始化")
        self.model = MyModel.get_model()
        self.tools = self.__init__tools()
        self.agent = self.__init__agent()

    def __init__tools(self):
        # sql_query_tool 只读护栏（非 SELECT 直接拦截）；
        # describe_table_tool 让 LLM 在不确定列名时自查
        self.tools = [sql_query_tool, describe_table_tool]
        return self.tools

    def __init__agent(self):
        # 提示词保持精简：防瞎编表名/列名靠 describe_table 工具自查，不靠 prompt 喊话
        prompt = """
        一:你是一个sql问题智能体,你有两个工具:sql_query_tool（只读查询）、describe_table（查表结构）
        二:工作流程:请严格按照以下步骤执行
            1.根据消息里的【表结构资料】查表/查数据
            2.列名不确定时，先用 describe_table 查实际列名再写 SQL
            3.查完后，把查询结果整理成"列名 + 数值"的资料文本输出（数据库返回的是裸元组，
              必须配上列名，否则下游分析智能体读不懂）；不要写总结和结论，那是分析智能体的活
            4.查询失败时，直接说明"查询失败：原因"，不要编造数据
        三:使用规则：
            1.只能进行select查询，不能进行delete操作
            2.多表查询，请使用join
            3.不要回答你的思考过程
        四:补充规则（表结构以消息里的【表结构资料】为准）:
            1.涉及"总共/一共"用SUM()；日期字段为 DATE/DATETIME，按时间区间过滤
            2.GROUP BY 严格匹配 SELECT 非聚合列（MySQL 5.7+ only_full_group_by）
            3.排名top用 order by + limit；只查询前5条数据
            4.时间口径：用户问题没指定时间范围时，默认按最近30天统计，并在结果里注明；
              问题已含时间（本月、2024年、最近7天等）以问题为准；TOP N/最高最低按全时段排名
        """
        # create_agent：一行建一个"能自主调工具的智能体"，
        # agent.invoke 时框架内部自动跑"模型思考→调工具→拿到结果→回答"循环
        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
            # 记忆由图的 Checkpoint 管，智能体不重复设
        )
        return agent

    def answer(self, question: str, schema_text: str) -> str:
        """收用户问题 + RAG 表结构资料，返回智能体整理好的"列名+数值"资料文本"""
        # 传入的消息是 HumanMessage：内容 = RAG查的表结构 + 用户问题
        rs = self.agent.invoke({
            "messages": [HumanMessage(content=f"【表结构资料】\n{schema_text}\n\n【用户问题】{question}")]
        })
        # 取最后一条 AI 消息 = 智能体按 prompt 第 3 步整理好的资料文本。
        # 不能取最后一条 tool 消息：它可能是 describe_table 的列名清单或 SQL 报错文本，
        # 而且是没配列名的裸元组，下游分析智能体读不懂。
        for m in reversed(rs["messages"]):
            if getattr(m, "type", "") == "ai" and str(m.content).strip():
                result = str(m.content)
                logger.info("查询完成：{} 字", len(result))
                return result
        return str(rs["messages"][-1].content)


if __name__ == '__main__':
    agent = SQLQuestionAgent()
    print(agent.answer("最近30天各酒店的入住率、ADR 和 RevPAR", "stay_record 表：stay_id, hotel_id, actual_check_in, nights, room_amount"))
