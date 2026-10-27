# SQLQuestionAgent SQL问题智能体：只读查库，把查询结果整理成"列名+数值"的资料文本。
# answer 收 metric_text（RAG 检索的指标口径/查询规范）；表名列名以 sql_query 工具说明为准。
# 骨架（建模型/建 agent）在 BaseToolAgent，这里只剩工具集 + prompt 配置 + answer。
from loguru import logger
from langchain_core.messages import HumanMessage

from app.ai.agent.registry import BaseToolAgent
from app.ai.tool.mysql_tool import sql_query_tool, describe_table_tool


class SQLQuestionAgent(BaseToolAgent):
    # sql_query_tool 只读护栏（非 SELECT 直接拦截）；
    # describe_table_tool 让 LLM 在不确定列名时自查
    tools = [sql_query_tool, describe_table_tool]

    # 提示词保持精简：防瞎编表名/列名靠 describe_table 工具自查，不靠 prompt 喊话
    system_prompt = """
    一:你是一个sql问题智能体,你有两个工具:sql_query_tool（只读查询）、describe_table（查表结构）
    二:工作流程:请严格按照以下步骤执行
        1.根据消息里的【指标口径与查询规范】+ sql_query 工具说明里的表清单写 SQL 查数
        2.列名不确定时，先用 describe_table 查实际列名再写 SQL
        3.查完后，把查询结果整理成"列名 + 数值"的资料文本输出（数据库返回的是裸元组，
          必须配上列名，否则下游分析智能体读不懂）；不要写总结和结论，那是分析智能体的活
        4.查询失败时，直接说明"查询失败：原因"，不要编造数据
    三:使用规则：
        1.只能进行select查询，不能进行delete操作
        2.多表查询，请使用join
        3.不要回答你的思考过程
    四:补充规则（指标口径以消息里的【指标口径与查询规范】为准；表名列名以 sql_query 工具说明为准）:
        1.涉及"总共/一共"用SUM()；日期字段为 DATE/DATETIME，按时间区间过滤
        2.GROUP BY 严格匹配 SELECT 非聚合列（MySQL 5.7+ only_full_group_by）
        3.排名top用 order by + limit；只查询前5条数据
        4.时间口径：用户问题没指定时间范围时，默认按最近30天统计，并在结果里注明；
          问题已含时间（本月、2024年、最近7天等）以问题为准；TOP N/最高最低按全时段排名
        5.资料里的 SQL 模板仅做参考：口径（公式/过滤条件）必须遵守，SQL 文本按实际问题改写
          时间范围/维度/门店，占位符不要照抄
    """

    def answer(self, question: str, metric_text: str) -> str:
        """收用户问题 + RAG 口径/规范资料，返回智能体整理好的"列名+数值"资料文本"""
        # 传入的消息是 HumanMessage：内容 = RAG查的口径资料 + 用户问题
        rs = self.agent.invoke({
            "messages": [HumanMessage(content=f"{metric_text}\n\n【用户问题】{question}")]
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
