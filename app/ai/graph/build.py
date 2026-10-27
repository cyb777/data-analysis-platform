# 建图层：把节点拼成图，配好记忆/缓存/重试。
# Checkpointer 优先 Redis 持久化（重启不丢对话历史），失败降级内存（见 _get_checkpointer）。
from langgraph.graph import StateGraph, START, END
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy, RetryPolicy
from loguru import logger

from app.ai.graph.state import State
from app.ai import nodes  # 物理平级：app/ai/nodes/ 和 app/ai/graph/ 同级
# 入口条件边要用（判断这轮要不要压缩历史），见下方 add_conditional_edges(START, ...)
from app.ai.mem.compress import should_compress

# 向量库（kb_43 知识库 / mem_43 对话记忆）由 build_graph() 启动期显式构建——不放在模块顶层，
# 否则任何 import 本模块的地方（单测、工具脚本）都会触发一次 embedding 调用 + Redis 连接。
from app.ai.rag import builder as rag_builder, retriever as rag_retriever
from app.ai.mem import history as mem_history


async def _get_checkpointer():
    """优先用 Redis 持久化 Checkpointer（重启不丢对话历史），失败降级为内存。

    注意这不是"Redis 挂了也能起"的保证：Redis 全挂时应用会更早死于
    build_graph() 的 build_vector_store()（编译前执行：_index_doc_count 吞异常
    → force_all=True → 全量重嵌时 add_texts 无 try 包裹直接抛）。本降级实际只在
    窄故障面触发——向量库能连、但 checkpoint 建不了（langgraph-checkpoint-redis
    包缺失 / 索引权限 / asetup 失败等）。

    必须用 AsyncRedisSaver 而不是同步 RedisSaver：应用全程走 astream，
    同步版没实现 aget_tuple 等异步方法（base 类直接抛 NotImplementedError）。
    """
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver
        # Redis 地址收口在 rag/builder.py 的 REDIS_HOST/REDIS_PORT 常量（改地址只动一处）
        redis_url = f"redis://{rag_builder.REDIS_HOST}:{rag_builder.REDIS_PORT}"
        saver = AsyncRedisSaver(redis_url)
        await saver.asetup()  # 建 checkpoint 索引
        logger.info("LangGraph Checkpointer：使用 Redis 持久化（对话记忆重启不丢）")
        return saver
    except Exception as e:
        logger.warning("Redis Checkpointer 初始化失败，降级 InMemorySaver（重启丢对话历史）：{}", e)
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()


async def build_graph():
    """启动编排：建向量库 → 注册 10 节点 → 配缓存/重试 → 连边 → compile（只被 lifespan 调一次）"""
    # 启动期显式建库并注入检索侧——"建库"只发生一次，运行期节点直接命中；
    # 测试场景没注入时，retriever 懒加载兜底自建。
    rag_retriever.set_vector_store(rag_builder.build_vector_store())
    logger.info("RAG 向量库（kb_43）建库完成，节点调 retrieve_schema 时直接拿")
    # 对话记忆冷层向量库（mem_43）：summarize 块提交写入、mem/recall 回查读取
    mem_history.set_memory_store(mem_history.build_memory_store())
    logger.info("记忆向量库（mem_43）就绪，summarize 块提交时原文直接入库")

    builder = StateGraph(State)

    # 节点注册（共 10 节点）
    # ======================
    # summarize：history 超阈值就压缩（挂在所有取数/写作节点之前，统一节流）
    builder.add_node("summarize", nodes.summarize_node)
    builder.add_node("route", nodes.route_node)

    # 统一缓存与重试策略
    # ==================
    # 注意两个机制：
    #   ① mysql_tool._run_sql 会把 SQL 异常吞成字符串返回（不抛异常），
    #     所以 RetryPolicy 对「SQL 写错」无效，retry 只兜网络层瞬时故障（超时/连接重置）；
    #   ② CachePolicy 默认对整个输入 state 哈希，多轮对话 history 每轮都变会永不命中，
    #     所以自定义 key_func 只取「用户 + 改写后问题」。
    #     key 必须带 user_id：否则不同用户问同样问题会命中同一缓存、拿到他人快照。
    def _fetch_cache_key(state):
        q = state.get("rewritten_q") or state.get("question", "")
        return f"{state.get('user_id', 0)}|{q}"

    def _retry(attempts: int, retry_on=(ConnectionError, TimeoutError)) -> RetryPolicy:
        # 重试次数少（这些节点每次都要跑完整 Agent，几十秒）；
        # backoff_factor=1.0 + jitter=False：固定间隔 1s，不搞指数退避
        return RetryPolicy(
            max_attempts=attempts,
            initial_interval=1.0,
            backoff_factor=1.0,
            jitter=False,
            retry_on=retry_on,
        )

    LLM_RETRY = _retry(2)
    builder.add_node(
        "rag", nodes.rag_node,
        # rag 检索的是表结构/业务口径，几乎不变，TTL 给长一些
        cache_policy=CachePolicy(ttl=300, key_func=_fetch_cache_key),
        retry_policy=_retry(3, retry_on=(ConnectionError,)),
    )
    builder.add_node(
        "db", nodes.db_node,
        # db 是最重的节点（检索 + SQLAgent 多轮 tool_call + 查库）；查业务数据，TTL 短一些
        cache_policy=CachePolicy(ttl=60, key_func=_fetch_cache_key),
        retry_policy=LLM_RETRY,
    )
    builder.add_node(
        "chart", nodes.chart_node,
        cache_policy=CachePolicy(ttl=180, key_func=_fetch_cache_key),
        retry_policy=LLM_RETRY,
    )
    builder.add_node("clarify", nodes.clarify_node)
    # 发邮件调度（HITL 拆双节点）：draft 起草（不发送）→ send 开头 interrupt 挂起等用户确认。
    # interrupt 恢复后节点会从头重跑，拆开是为了让「起草的 LLM 调用」不被重跑，
    # 草稿经 state.email_draft 跨断点传递。
    builder.add_node("system_draft", nodes.system_draft_node)
    builder.add_node("system_send", nodes.system_send_node)
    builder.add_node("writer", nodes.writer_node)
    # chat 节点：route 直派的对话式追问，单次模型调用直接回答（不汇入 writer）。
    # 不配缓存：回答依赖每轮都变的 history，没有命中价值。
    builder.add_node("chat", nodes.chat_node)

    # 入口条件边：只在攒够一块时才进 summarize 节点
    # =============================================
    # should_compress 是纯本地判断，放条件边里零成本；
    # 否则前 54 轮也会空跑一次节点，前端还多推一条 status 提示。
    builder.add_conditional_edges(
        START,
        lambda s: "summarize"
        if should_compress(s.get("history", []), s.get("summary_upto", 0),
                           s.get("history_deleted", 0))
        else "route",
        {"summarize": "summarize", "route": "route"},
    )
    # 压缩完仍然汇入 route，保持「所有请求都经过路由分发」这条不变
    builder.add_edge("summarize", "route")

    # 节点 → 边映射（【关键】add_node 的节点名必须和下面映射里写的完全一致，
    # 改了节点名两边都要改）：
    #   route（意图路由） → 6 条边：
    #       db           数据查询 → db 节点
    #       chart        图表/可视化/对比分析 → chart 节点（对比类问题由 chart 出分组/多系列图）
    #       rag          业务知识问答 → rag 节点
    #       system       发邮件/调度 → system_draft 节点
    #       clarify      信息不足 → clarify 节点（反问后等用户补充）
    #       chat         闲聊/通用问答 → chat 节点
    #       end          越权拦截（db/chart 仅高级员工）→ route 已自写 answer，直连 END
    builder.add_conditional_edges("route", lambda s: s["route"], {
        "rag": "rag",
        "db": "db",
        "chart": "chart",
        "clarify": "clarify",
        "system": "system_draft",
        # chat 出口指向 chat 节点（对话式追问）；writer 节点只接收数分支的汇总
        "chat": "chat",
        "end": END,
    })

    # 资料节点汇到 writer 写最终回答
    builder.add_edge("rag", "writer")
    builder.add_edge("db", "writer")
    builder.add_edge("chart", "writer")
    # HITL：起草完进发送节点（里面 interrupt 挂起等确认）；
    # system_send 三分支（确认/取消/起草失败）都在节点内自写 answer 直连 END，不经 writer
    builder.add_edge("system_draft", "system_send")
    builder.add_edge("system_send", END)
    # clarify 直接到 END：反问完就结束，本轮不再查库分析，等用户下一轮补充
    builder.add_edge("clarify", END)
    builder.add_edge("writer", END)
    # chat 答完直接结束（同 clarify）
    builder.add_edge("chat", END)

    # Checkpointer 优先 Redis 持久化（_get_checkpointer 兜底退内存）
    return builder.compile(
        checkpointer=await _get_checkpointer(),
        cache=InMemoryCache(),
    )
