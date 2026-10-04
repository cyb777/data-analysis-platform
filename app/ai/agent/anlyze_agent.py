# =========================================================
# AnlyzeAgent 数据分析智能体
# 定位：纯 writer——基于前序节点查好的资料 + 对话历史，做综合分析并生成最终回答。
#   不挂查库工具：资料由前序节点（rag/db/chart/system）查好喂给它。
# 工具：只留 data_calc_tool（增长率/占比/CAGR 三类容易算错的）；
#   简单算术（求和/平均/最值/排序）直接心算，不调工具。
# =========================================================
from loguru import logger
from app.ai.model.model import MyModel
from app.ai.tool.data_calc_tool import data_calc_tool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage


class AnlyzeAgent:
    def __init__(self):
        logger.info("初始化数据分析智能体")
        #初始化模型
        self.model = MyModel.get_model()
        #调用私有方法，初始化工具列表
        self.tools = self.__init__tools()
        # 记忆由图统一管理，Agent 不重复设 checkpointer；
        # create_agent 提前到 __init__ 建一次，避免每次调用 answer 重建
        self.agent = self.__init__agent()

    #私有方法
    def __init__tools(self):
       # 只挂 data_calc_tool（定位见文件头）。
       self.tools = [data_calc_tool]
       #返回工具列表，供智能体使用
       return self.tools

    def __init__agent(self):
        # 定义系统提示词（"详细分析+结论分析"格式规则 + 工具调用规则）
        prompt = """
        一:你是一个数据分析智能体,你有一个工具：
            1. data_calc_tool：只处理三类容易算错的计算——增长率、占比、CAGR复合增长率。
               求和/平均/最值/排序这类简单算术请直接心算，不要调工具。
            【重要】你不能再查数据库。所有资料都由前序节点查好放在【相关资料】里，
            资料不足就直接说"当前资料不足以回答"，不要编造、不要假设数据。
        二:工作流程:请严格按照以下步骤执行
        1.根据【相关资料】整理数据；资料不足时直说，不要自己造数
        2.【效率要求·重要】资料里已有的数字直接用，简单算术（求和、占比、增长率、排序）直接心算写出结果，
          不要为此调用任何工具。只有 CAGR 复合增长率这类开方运算才调 data_calc_tool。
        3.Markdown 表格、KPI 列表直接手写输出。
        4.如果相关资料里有图表JSON，用一句话说明图表讲了什么（图表由图表智能体生成，你不需要再生成）
        5.输出格式（用户意图优先，三段式只是默认）：
            【开放式数据问题】（如"分析一下XX"、"XX情况怎么样"）严格按 3 段输出：
            ① 关键数据：3 行内（数字 + 排名，例"OCC 72%、ADR 318 元、RevPAR 229 元，XX 店排名第一"）
            ② 趋势分析：2-3 行（变化方向 + 可能原因，如 OTA 占比变化、节假日拉动、差评影响）
            ③ 业务建议：2-3 条可执行 action（例"加强会员直销渠道占比""推进未闭环投诉的处理""控制 OTA 佣金成本"）
            【指向明确的追问】（如"具体怎么做"、"只要给建议"、"为什么会跌"）：
            用户问什么就答什么——只问建议就直接列 action，只问原因就只讲原因。
            不要凑齐三段，也不要重复罗列对方在上一轮已经看过的数据。
          【重要】不要输出"数据来源"段落——不要罗列查了哪几张表、用了什么 SQL、
          怎么关联的、图表由谁渲染（比如不要写出
          "stay_record 关联 hotel，按 actual_check_in 聚合间夜，再除以可售房数…"
          这种技术描述）。用户要的是结论和建议，不是执行细节。
        三:重要规则
        1.资料里没有的就直说不知道，不要编造；数据问题先给结论，再给关键数字
        2.【效率要求·重要】能一轮答完就不要多轮。资料够用时直接输出最终回答，不要为了"更严谨"而反复调工具。
        """
        # create_agent：建"能自主调工具的智能体"；不设 response_format → 纯文本输出（SSE 流式最稳）
        agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
        )
        return agent


    def answer(self, question: str, context: str, history_text: str,
               extra_instruction: str = "") -> str:
        """收问题 + 前序节点资料 + 对话历史，返回最终回答（纯文本）。

        extra_instruction：调用方注入的本次输出要求（拼在消息末尾、优先级最高），
        默认空——通用问答不受影响；特殊场景（如写邮件）由调用方临时约束格式。
        """
        try:
            # 调用智能体：把"前面节点查到的资料 + 对话历史 + 问题"一起喂给它
            content = (
                f"【相关资料】\n{context}\n\n"
                f"【对话历史】\n{history_text}\n\n"
                f"【用户问题】\n{question}"
            )
            if extra_instruction:
                content += f"\n\n【本次输出要求·最高优先级】\n{extra_instruction}"
            # 调用智能体：把"前面节点查到的资料 + 对话历史 + 问题"一起喂给它
            response = self.agent.invoke(
                {"messages": [HumanMessage(content=content)]},
            )
            # 纯文本智能体没有结构化输出，最后一条消息就是最终回答文字
            # （response["messages"]：这一轮的所有消息，[-1] 取最后一条）
            data = str(response["messages"][-1].content)
            logger.info("回答完成：{} 字", len(data))
            return data
        except Exception as e:
            logger.error(e)
            return f"（分析失败）{type(e).__name__}"


if __name__ == '__main__':
    agent = AnlyzeAgent()
    print(agent.answer("最近30天入住率和 RevPAR 怎么样", "查询结果：OCC 72%，ADR 318 元，RevPAR 229 元，间夜 2160", "（暂无）"))
