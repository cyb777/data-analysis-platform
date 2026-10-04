# LangGraph 10 个节点的实现层：每个节点一个文件，build.py 负责把它们串成图。
#   summarize      对话历史压缩（超长时把旧对话压成摘要，防止 token 爆掉）
#   route          意图路由（6 选 1：db / chart / rag / system / clarify / chat）
#   rag            业务知识检索（向量+BM25 混合检索，命中口径文档直接答）
#   db             SQL 取数（SQLQuestionAgent + mysql_tool）
#   chart          ECharts 出图（EchartsAgent，对比类问题也走这里出分组/多系列图）
#   system_draft   邮件草稿生成（写完草稿后图挂起，等用户确认）
#   system_send    邮件发送（HITL：用户确认后才真正群发）
#   clarify        澄清反问（信息不足时反问，而非瞎猜）
#   writer         分析结论撰写（AnlyzeAgent 把数据/图表整理成业务分析）
#   chat           闲聊兜底（与业务无关的对话由 LLM 直接应答）
from app.ai.nodes.summarize import summarize_node
from app.ai.nodes.route import route_node
from app.ai.nodes.rag import rag_node
from app.ai.nodes.db import db_node
from app.ai.nodes.chart import chart_node
from app.ai.nodes.clarify import clarify_node
from app.ai.nodes.system_draft import system_draft_node
from app.ai.nodes.system_send import system_send_node
from app.ai.nodes.writer import writer_node
from app.ai.nodes.chat import chat_node

__all__ = [
    "summarize_node", "route_node", "rag_node", "db_node", "chart_node",
    "clarify_node", "system_draft_node", "system_send_node", "writer_node", "chat_node",
]
