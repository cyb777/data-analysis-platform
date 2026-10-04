"""summarize 节点：分块压缩（每轮进来先看是否攒够一块）

物理位置：app/ai/nodes/（和 graph/ 平级）
三层记忆中负责温层写入：compressed_summary（块拼接）+ memory_facts（同 key 覆盖）。
"""
import redis
from loguru import logger
from langchain_core.runnables import RunnableConfig

from app.ai.graph.context_compressor import (
    compress_chunk, merge_facts,
    KEEP_RECENT, MAX_HISTORY_SOFT_CAP,
)
from app.ai.model.model import MyModel

# ============================================================
# 模块级资源（进程内复用，不随每轮 state 重建）
# ============================================================

# 压缩历史用轻量模型（同 route 节点，见 MyModel.get_route_model）
_llm = MyModel.get_route_model()

# 压缩失败退避：TTL 600s，不进 state（临时熔断状态不污染业务快照）
_BACKOFF_TTL = 600
_redis = redis.Redis(host="127.0.0.1", port=6379, db=0)


def summarize_node(state, config: RunnableConfig = None):
    """分块压缩节点（能进来说明 build.py 条件边已判定攒够一块）：
    - 只压新增块 history[summary_upto:-5]，旧块封存只追加；事实同 key 覆盖
    - 失败置 Redis 退避 600s（退避期已有块/事实/热层照常使用）
    """
    history = state.get("history", [])
    summary_upto = state.get("summary_upto", 0)

    # ---------- ① 软上限监控：不截断，靠日志发现 checkpointer 异常增长 ----------
    if len(history) > MAX_HISTORY_SOFT_CAP:
        logger.warning(
            f"⚠️ history 已达 {len(history)} 轮，超过软上限 {MAX_HISTORY_SOFT_CAP}；"
            f"checkpointer 体积可能在涨，请关注"
        )

    # ---------- ② 取 thread_id，构造退避键 ----------
    thread_id = ""
    try:
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
    except AttributeError:
        pass

    # ---------- ③ Redis 退避检查：退避期内跳过（RedisError 不阻塞，照常压缩） ----------
    backoff_key = f"summarize:backoff:{thread_id}" if thread_id else ""
    try:
        if backoff_key and _redis.exists(backoff_key):
            logger.info(f"  → summarize：退避期内（{thread_id}），跳过压缩")
            return {}
    except redis.RedisError as e:
        # Redis 本身挂了不能阻塞业务：退一步照常尝试压缩
        logger.warning(f"  → summarize：查询退避键失败，继续压缩：{e}")

    # ---------- ④ 切出新块并压缩：切点 history[summary_upto:-5]，最近 5 轮不封存 ----------
    chunk = history[summary_upto:len(history) - KEEP_RECENT]
    logger.info(
        f"  → summarize：当前 {len(history)} 轮，压缩第 {summary_upto + 1}"
        f"~{summary_upto + len(chunk)} 轮（{len(chunk)} 轮一块）"
    )
    chunk_summary, new_facts = compress_chunk(_llm, chunk, summary_upto + 1)
    # ---------- ⑤ 压缩失败：置退避 600s，本轮不写 state ----------
    if not chunk_summary:
        if backoff_key:
            try:
                _redis.set(backoff_key, 1, ex=_BACKOFF_TTL)
                logger.warning(f"  → summarize：压缩失败，置退避 {_BACKOFF_TTL}s（{thread_id}）")
            except redis.RedisError as e:
                logger.error(f"  → summarize：置退避键也失败：{e}")
        return {}

    # ---------- ⑥ 写温层：摘要只追加拼接、事实同 key 覆盖、推进 summary_upto ----------
    old_summary = state.get("compressed_summary", "")
    summary = (old_summary + "\n" + chunk_summary) if old_summary else chunk_summary
    facts = merge_facts(state.get("memory_facts", []), new_facts)
    new_upto = summary_upto + len(chunk)
    return {
        "compressed_summary": summary,
        "memory_facts": facts,
        "summary_upto": new_upto,
    }
