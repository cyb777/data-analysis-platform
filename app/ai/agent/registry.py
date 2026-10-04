# 智能体实例注册中心：所有节点统一从这里 import 实例，保证进程内单例。
# 节点文件各自实例化会重复构造；测试时可整体替换：registry.sql_agent = Mock()。
from loguru import logger

from app.ai.agent.sql_question_agent import SQLQuestionAgent
from app.ai.agent.echarts_agent import EchartsAgent
from app.ai.agent.anlyze_agent import AnlyzeAgent
from app.ai.agent.email_dispatcher import EmailDispatcher

# ====== 进程内单例（图执行时节点直接调用）======
sql_agent = SQLQuestionAgent()
echarts_agent = EchartsAgent()
anlyze_agent = AnlyzeAgent()
email_dispatcher = EmailDispatcher()  # 邮件调度器

logger.info("智能体注册中心初始化完成：SQLQuestion / Echarts / Anlyze / EmailDispatcher（4 个）")
