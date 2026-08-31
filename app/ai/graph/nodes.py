"""节点层：图负责编排（路由/记忆/缓存/重试），节点负责调用智能体干活。

五个节点：route / rag / db / chart / llm
  db  → SQLQuestionAgent（查库）   chart → EchartsAgent（图表）
  llm → AnalyzeAgent（综合分析汇总）   rag/route → 图内逻辑（RAG 是管线不是智能体）
"""
import os

from loguru import logger
from langchain_core.prompts import ChatPromptTemplate

from app.ai.model.model import MyModel
from app.ai.schema.route_schema import Route
from app.ai.rag.knowledge_base import retrieve_schema
from app.ai.agent.sql_question_agent import SQLQuestionAgent
from app.ai.agent.echarts_agent import EchartsAgent
from app.ai.agent.analyze_agent import AnalyzeAgent

llm = MyModel.get_model()
# 智能体实例（图执行时节点直接调用，复用同一个对象）
sql_agent = SQLQuestionAgent()
echarts_agent = EchartsAgent()
analyze_agent = AnalyzeAgent()


# ==================== 节点 ====================

def route_node(state):
    """路由节点：LLM 按【语义】判断走哪条路"""
    q = state["question"]
    history = state.get("history", [])
    history_text = "\n".join(f"用户：{x}\n助手：{y}" for x, y in history) or "（暂无）"

    prompt = ChatPromptTemplate.from_template(
        """你是智能路由判断器，根据用户问题的【语义】决定走哪条路，只能输出一个词：
        - rag：问指标口径/定义/业务知识的问题（如"复购率怎么定义""销售额的口径"）
        - db：要查具体数据的问题（销售额、排名、客户、订单等，文字回答即可）
        - chart：要求画图/可视化/图表分析的问题（"画个柱状图""做个趋势图"）
        - llm：普通聊天、总结、以及其他问题
        如果问题里有代词指代前文提到的人或事（如"它""那个产品"），结合对话历史判断。
        对话历史：{history}
        用户问题：{question}
        请只输出 rag、db、chart、llm 中的一个词。"""
    )
    # with_structured_output 让模型输出 Route 结构（只准填 branch 一词，防自由发挥）
    # (prompt | route_model) 链式：模板填好 → 模型 → .branch 取分支词
    route_model = llm.with_structured_output(Route)
    branch = (prompt | route_model).invoke({"question": q, "history": history_text}).branch

    if branch not in ("rag", "db", "chart", "llm"):   # 容错兜底：模型抽风就走 llm
        logger.warning(f"  → 模型路由返回异常值：{branch}，兜底走 llm")
        branch = "llm"
    logger.info(f"  → 模型路由判断「{q[:20]}...」走：{branch} 分支")
    return {"route": branch}


def rag_node(state):
    """RAG 节点：问指标口径时，去知识库检索相关定义，写进 context（配缓存/重试见 build_graph）"""
    q = state["question"]
    context = retrieve_schema(q)
    logger.info("  → rag 节点拿到 {} 段口径资料", context.count("---"))
    # 模拟一次偶发的网络抖动：让 RetryPolicy 派上用场（真实场景里 RAG 调 embedding 就可能抖）
    if os.getenv("DEMO_RAG_RETRY") == "1":
        import random
        if random.random() < 0.5:
            raise ConnectionError("RAG 检索网络抖动（模拟）")
    return {"context": context}


def db_node(state):
    """数据库节点（SQLQuestionAgent）：RAG 检索表结构 → 智能体写 SQL 查库 → 结果写进 context"""
    q = state["question"]
    schema = retrieve_schema(q)                 # ① RAG 检索：这问题涉及哪些表
    result = sql_agent.answer(q, schema)        # ② SQL 智能体：查库（只读护栏在工具层）
    return {"context": f"用户问题:{q}\n涉及的表结构:\n{schema}\n数据库查询结果:\n{result}"}


def chart_node(state):
    """图表节点（EchartsAgent）：RAG 检索 → 智能体查库 + 生成 ECharts JSON"""
    q = state["question"]
    schema = retrieve_schema(q)                 # ① RAG 检索表结构
    chart_json = echarts_agent.answer(q, schema)  # ② 图表智能体：查库 + 结构化输出 ChartData

    # 图表 JSON 单独写进 state.chart_json（API 层直接推给前端渲染，不混进回答文字里）
    return {
        "context": f"用户问题:{q}\n涉及的表结构:\n{schema}\n图表JSON:\n{chart_json}",
        "chart_json": chart_json,
    }


def llm_node(state):
    """回答节点（AnalyzeAgent）：综合分析资料 + 对话历史，生成最终回答"""
    question = state["question"]
    context = state.get("context", "")
    history = state.get("history", [])
    history_text = "\n".join(f"用户：{x}\n助手：{y}" for x, y in history) or "（暂无）"

    answer = analyze_agent.answer(question, context, history_text)
    # 把这轮"问+答"追加进 history，Reducer 自动累加而不是覆盖
    return {"answer": answer, "history": [(question, answer)]}
