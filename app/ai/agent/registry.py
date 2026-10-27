# 智能体实例注册中心：所有节点统一从这里 import 实例，保证进程内单例。
# 节点文件各自实例化会重复构造；测试时可整体替换：registry.sql_agent = Mock()。
#
# 同收两样基建：
#   BaseToolAgent —— sql/echarts/anlyze 三 agent 的同构骨架基类；
#   invoke_with_structured_retry —— echarts/email_dispatcher 共用的结构化输出重试。
# 【顺序即契约】两样基建必须先于下方四个 agent import 定义：四个 agent 文件从本模块
# import 它们，registry ↔ agent 循环 import 靠"先定义后引用"成立；因此 agent 文件
# 不应绕过 registry 被直接 import（头一行"统一从这里 import"的约定本来就如此）。
from loguru import logger
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from app.ai.model.model import MyModel


class BaseToolAgent:
    """工具智能体基类：子类只声明三样类属性配置，answer() 出入参各异留子类。"""

    # 子类配置区（类属性；本文件底部无参构造、测试整体 Mock 替换实例，不走 __init__ 传参）
    # ====================================================================================
    tools: list = []            # 挂给智能体的工具集
    system_prompt: str = ""     # 系统提示词
    response_format = None      # 结构化输出 schema（不配则纯文本输出）

    def __init__(self):
        logger.info("{}初始化", type(self).__name__)
        # create_agent 提前到 __init__ 建一次（图节点反复调 answer，不每次重建）；
        # 记忆由图的 Checkpoint 统一管理，智能体不重复设
        self.agent = create_agent(
            model=MyModel.get_model(),
            tools=self.tools,
            system_prompt=self.system_prompt,
            response_format=self.response_format,
        )


def invoke_with_structured_retry(agent, content: str, retries: int = 3, label: str = "agent"):
    """调 agent 取 structured_response，缺结构或异常统一都重试。

    模型偶发"不调结构化工具、直接输出纯文本"（返回里没有 structured_response 键，
    直接取会 KeyError）；API/网络异常也偶发——重试几次通常就正常。
    :return: (structured, None) 成功；(None, last_err) 全部失败，err 交调用方拼兜底
    """
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            response = agent.invoke({"messages": [HumanMessage(content=content)]})
            # 防御性取键：response.get() 拿不到返回 None，不像 [] 直接抛 KeyError
            structured = response.get("structured_response")
            if structured is not None:
                return structured, None
            last_err = "模型多次未按结构化格式输出（structured_response 缺失）"
            logger.warning("{} 第{}次未拿到结构化输出，重试", label, attempt)
        except Exception as e:
            last_err = e
            logger.warning("{} 第{}次调用出错：{}，重试", label, attempt, e)
    return None, last_err


# 四个 agent 实现（import 时各自回拿上面已定义的 BaseToolAgent / helper）
# =======================================================================
from app.ai.agent.sql_question_agent import SQLQuestionAgent
from app.ai.agent.echarts_agent import EchartsAgent
from app.ai.agent.anlyze_agent import AnlyzeAgent
from app.ai.agent.email_dispatcher import EmailDispatcher

# 进程内单例（图执行时节点直接调用）
# ==================================
sql_agent = SQLQuestionAgent()
echarts_agent = EchartsAgent()
anlyze_agent = AnlyzeAgent()
email_dispatcher = EmailDispatcher()  # 邮件调度器

logger.info("智能体注册中心初始化完成：SQLQuestion / Echarts / Anlyze / EmailDispatcher（4 个）")
