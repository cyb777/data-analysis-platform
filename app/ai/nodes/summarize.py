"""summarize 节点：分块压缩 + 冷层入库 + 热层延迟截断（每轮进来先看是否攒够一块）

温层写入 = compressed_summary 块拼接 + memory_facts 同 key 覆盖；
冷层写入 = 已压块原文 embedding 入 mem_43（见 mem/history.py）。
对外入口只有 summarize_node（build.py 注册成节点，跟在 should_compress 条件边后面）；
_llm / _backoff_local / _in_backoff / _TRUNCATE 都是内部件。

块提交原子语义（三件套要么全成要么全不成——靠顺序 + 幂等收敛，不是事务）：
  1. compress_chunk 压摘要  2. embed_turns 原文入 mem_43（key 幂等，重试覆盖不翻倍）
  3. 全成才一次性写 state（摘要/事实/推进 upto）；任一失败不写 state、置退避 600s

history 延迟截断：入库后原文留作备份，len(history) 超 HISTORY_HARD_LIMIT 才删最老一块；
删除量 ≤ upto（只删已入库的轮次），失败时 upto 停走、未入库的不删（失败缓冲带）。
不支持 legacy 老线程（冷层未向量化的旧 checkpoint）：部署时一次性清空。
"""
import time

from loguru import logger
from langchain_core.runnables import RunnableConfig

from app.ai.mem import history as mem_history
from app.ai.mem.compress import (
    compress_chunk, merge_facts,
    CHUNK_SIZE, KEEP_RECENT, HISTORY_HARD_LIMIT,
)
from app.ai.model.model import MyModel

# 模块级资源（进程内复用，不随每轮 state 重建）
# =============================================

# 压缩失败进程内退避 600s：挡住"失败后每轮空烧一次压缩 LLM"。单进程部署，重启即清（顶多补烧一次）
_BACKOFF_TTL = 600
_backoff_local: dict = {}   # {thread_id: 到期 monotonic}

# 压缩历史用主模型（timeout=80；route 轻量实例 25s 对 50 轮压缩系统性不足，实测三次全超时）
_llm = MyModel.get_model()

# history 截断哨兵（reducer 见 graph/state.append_history；keep 必须 int）
_TRUNCATE = "__truncate__"


# 内部件：退避检查（进程内字典，600s）
# ====================================
def _in_backoff(thread_id: str) -> bool:
    """退避期内 → True；过期的顺手清掉，防字典无界增长。"""
    exp = _backoff_local.get(thread_id, 0)
    if exp <= time.monotonic():
        _backoff_local.pop(thread_id, None)
        return False
    logger.info(f"  → summarize：退避期内（{thread_id}），跳过压缩")
    return True


# 节点本体：build.py 条件边（should_compress）判定攒够一块才进来
# ================================================================
def summarize_node(state, config: RunnableConfig = None):
    """分块压缩节点（能进来说明 build.py 条件边已判定攒够一块）"""
    # upto = 全局轮次锚（严禁当列表下标）；deleted = 已累计哨兵删除的轮次；
    # thread_id 取值口径统一在 mem/history.thread_id_of
    history = state.get("history", [])
    upto = state.get("summary_upto", 0)
    deleted = state.get("history_deleted", 0)
    thread_id = mem_history.thread_id_of(config)

    # 退避期内直接放行（600s 不重试，挡住"失败后每轮空烧一次压缩 LLM"）
    if thread_id and _in_backoff(thread_id):
        return {}

    # 切块 = 未压尾部除去最近 5 轮；下标 = 全局轮次 - 已删轮次
    # （与条件边 should_compress 同一公式，这里不足一块属兜底守卫）
    start = upto - deleted
    end = len(history) - KEEP_RECENT
    chunk = history[start:end]
    if len(chunk) < CHUNK_SIZE:
        logger.info(f"  → summarize：未压部分 {len(chunk)} 轮不足 {CHUNK_SIZE}，本轮不压")
        return {}
    # start_turn = 块首的全局轮次（日志 + 冷层幂等 key 用）
    start_turn = upto + 1
    logger.info(f"  → summarize：当前 {len(history)} 轮，压缩第 {start_turn}~{upto + len(chunk)} 轮")
    # 1. 压缩：主模型结构化输出（compress.py 内 3 次重试，全败返回空）
    chunk_summary, new_facts = compress_chunk(_llm, chunk, start_turn)

    # 2. 入库 + 失败收口：压缩/入库任一失败都不写 state、置退避，下轮切同一块重压（key 幂等不翻倍）；
    # 无 thread_id 的离线路径跳过入库与截断（只做摘要+事实+推进 upto），单测不破
    ok = bool(chunk_summary)
    if ok and thread_id:
        ok = mem_history.embed_turns(thread_id, chunk, start_turn)
    if not ok:
        # 置退避 = 记到期时间
        if thread_id:
            _backoff_local[thread_id] = time.monotonic() + _BACKOFF_TTL
            logger.warning(f"  → summarize：失败置退避 {_BACKOFF_TTL}s（{thread_id}）")
        return {}

    # 3. 全成才提交：摘要追加 + 事实合并 + upto 推进一整块
    old = state.get("compressed_summary", "")
    result = {
        "compressed_summary": (old + "\n" + chunk_summary) if old else chunk_summary,
        "memory_facts": merge_facts(state.get("memory_facts", []), new_facts),
        "summary_upto": upto + len(chunk),
    }
    # 延迟截断：超 HARD_LIMIT 才用哨兵删最老一块（只删已入库轮次），deleted 同步累加；
    # keep = 截断后保留的轮数
    if thread_id and len(history) > HISTORY_HARD_LIMIT:
        keep = len(history) - len(chunk)
        result["history"] = [(_TRUNCATE, keep)]
        result["history_deleted"] = deleted + len(chunk)
        logger.info(f"  → summarize：超上限 {HISTORY_HARD_LIMIT}，删最老 {len(chunk)} 轮（留最近 {keep} 轮）")
    return result
