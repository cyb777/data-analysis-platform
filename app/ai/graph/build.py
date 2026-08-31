"""建图层：把节点装配成可执行的图，并配置记忆、缓存与重试策略。"""
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy, RetryPolicy

from app.ai.graph.state import State
from app.ai.graph import nodes


def build_graph():
    # StateGraph(State)：建"流水线图"，数据包按 State 模板走
    builder = StateGraph(State)

    builder.add_node("route", nodes.route_node)
    builder.add_node(
        "rag", nodes.rag_node,
        # 同一问题 30 秒内重复提问直接返回缓存结果，避免重复的 embedding 调用
        cache_policy=CachePolicy(ttl=30),
        # 网络类错误自动重试，最多 3 次，间隔递增（1s → 2s）
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_interval=1.0,
            backoff_factor=1.0,
            jitter=False,
            retry_on=(ConnectionError,),   # 只对网络类错误重试
        ),
    )
    builder.add_node("db", nodes.db_node)
    builder.add_node("chart", nodes.chart_node)
    builder.add_node("llm", nodes.llm_node)

    builder.add_edge(START, "route")

    # 条件边：按 route 节点写入的分支值分流到不同处理节点
    builder.add_conditional_edges("route", lambda s: s["route"], {
        "rag": "rag",
        "db": "db",
        "chart": "chart",
        "llm": "llm",
    })

    # 查完资料都汇到 LLM 生成回答
    builder.add_edge("rag", "llm")
    builder.add_edge("db", "llm")
    builder.add_edge("chart", "llm")
    builder.add_edge("llm", END)

    # checkpointer：每轮结束保存状态快照，同一 thread_id 再次请求时恢复历史（内存存储，重启丢失）
    # cache：给 CachePolicy 提供缓存后端
    return builder.compile(
        checkpointer=InMemorySaver(),
        cache=InMemoryCache(),
    )
