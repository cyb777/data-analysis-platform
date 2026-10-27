"""对话记忆冷层向量库（mem_43）：块原文 embedding 入库 + 语义回查。

与 kb_43 同一条向量管线、另一个索引：embedding 实例 / RediSearch schema / rerank 全部复用 rag 包。
写入方：summarize 节点（块提交三件套之一，见 nodes/summarize.py）；
读取方：mem/recall.py（冷层语义回查），业务节点不直接调本模块。

对外入口只有三个，其余（mem_tag / _turn_key / store 装配三件套）都是内部零件：
  embed_turns   写入——唯一调用方 nodes/summarize.py（压完块原文入冷层）
  mem_recall    读取——唯一调用方 mem/recall.py 的 recall_text（chat 专属冷层回查）
  thread_id_of  公共口径——summarize 与 recall 都靠它从 config 取线程 id（thread_id 不重复存进 state）

索引里每条 hash = 一轮问答：
  text 字段 = "【YYYY-MM-dd HH:mm】用户：{q}\n助手：{a}"（时间戳写进文本，回查展示直接用——
              "我昨天下午说的"比"第53轮"更接近用户表达）
  key      = f"mem_43:{sha1(thread_id + ':' + n)[:16]}"（确定性，同 (线程, 轮次) 重压覆盖不翻倍）
  tag      = mem_{sha1(thread_id)[:16]}（线程隔离；thread_id 含 :/@/. 会炸 RediSearch
              TAG 查询语法，故哈希化成纯 [a-z0-9_]——裸拼 filter 不转义，值里不能有任何标点）
"""
import hashlib
import threading

from loguru import logger

from app.ai.rag import builder, retriever

MEM_INDEX_NAME = "mem_43"   # RediSearch 索引名（与 kb_43 一条管线、两个索引）
RECALL_POOL_K = 10          # 语义回查向量路候选数（单线程语料少，10 足够进 rerank）

# 记忆库实例管理：启动期注入优先、懒加载兜底、双检锁线程安全
# ==============================================================
# 正常路径：build.py 启动期 build_memory_store() 建好 → set_memory_store() 注入——
# 建库要调 embedding（花钱）+ 连 Redis（副作用），不放模块顶层，否则任何 import 都触发一次；
# 也不每轮新建（实例进程内复用）。
# 兜底路径：没注入（单测/离线脚本）时首次使用经 _get_memory_store() 懒加载自建。
_memory_store = None
_memory_store_lock = threading.Lock()


def set_memory_store(vs) -> None:
    """启动期由 build.py 注入建好的记忆库（模式同 retriever.set_vector_store）"""
    global _memory_store
    _memory_store = vs


def _get_memory_store():
    """双检锁拿记忆库：第一道 if 无锁快读（挡住已建好的绝大多数调用，不然每次入库/回查都抢锁白付开销）；
    抢到锁后第二道 if 再验一次——防并发首发重复建库（两线程同时穿过第一道时只有一个真建）。"""
    global _memory_store
    if _memory_store is None:
        with _memory_store_lock:
            if _memory_store is None:  # 第二道检查：抢到锁再验一次
                _memory_store = build_memory_store()
    return _memory_store


def build_memory_store():
    """创建/连接 mem_43 索引（schema 与 kb_43 同一条管线）。启动期由 build.py 调一次"""
    return builder.make_vector_store(MEM_INDEX_NAME)


# 线程三小件：mem_tag（线程隔离 tag）/ thread_id_of（config 取线程，记忆域公共口径）/ _turn_key（幂等 key）
# ==================================================================================================
def mem_tag(thread_id: str) -> str:
    """线程 → 记忆索引的过滤 tag（sha1 哈希化；入库与回查共用同一生成函数，天然对应）"""
    return f"mem_{hashlib.sha1(thread_id.encode('utf-8')).hexdigest()[:16]}"


def thread_id_of(config) -> str:
    """从 config 取当前线程 id（thread_id 本来就在 config，不重复存进 state）。
    记忆域统一取值口径；缺失或畸形 config 返回 ""——调用方据此识别"离线直连"。
    """
    try:
        return (config or {}).get("configurable", {}).get("thread_id", "") or ""
    except AttributeError:
        return ""   # config 不是 dict（畸形调用）——同样按"离线直连"处理


def _turn_key(thread_id: str, n: int) -> str:
    """第 n 轮的确定性 Redis key：同 (线程, 轮次) 重复写覆盖同一 hash，幂等不翻倍"""
    return f"{MEM_INDEX_NAME}:{hashlib.sha1(f'{thread_id}:{n}'.encode('utf-8')).hexdigest()[:16]}"


# 对外入口：embed_turns 写入（summarize 专属）/ mem_recall 读取（chat 经 recall_text）
# ========================================================================================
def embed_turns(thread_id: str, turns: list, start_turn: int) -> bool:
    """把若干轮问答写入 mem_43（块提交三件套之一）。任一批次失败返回 False（调用方置退避）。

    turns: history 原始段 [(q, a, ts), ...]；start_turn: 第一轮的全局轮次。
    key 幂等：同一块重复提交覆盖同 hash，不翻倍——所以失败重试/legacy 迁移都安全。
    注意 start_turn 只用于幂等键（轮次是内部坐标）；文本里带的是时间戳不是轮次。
    """
    if not thread_id or not turns:
        return False
    tag = mem_tag(thread_id)
    texts, metas, keys = [], [], []
    for i, (q, a, ts) in enumerate(turns):
        n = start_turn + i
        texts.append(f"【{ts}】用户：{q}\n助手：{a}")
        metas.append({"tag": tag})
        keys.append(_turn_key(thread_id, n))
    try:
        vs = _get_memory_store()
        builder.add_texts_batched(vs, texts, metas, keys)
        logger.info(
            f"  → mem_43 入库 {len(texts)} 轮（{thread_id} 第{start_turn}"
            f"~{start_turn + len(texts) - 1}轮）"
        )
        return True
    except Exception as e:
        logger.error(f"  → mem_43 入库失败（{thread_id}，{len(texts)} 轮）：{e}")
        return False


def mem_recall(question: str, thread_id: str, top_k: int = 2) -> str:
    """语义回查：在本线程的记忆向量里找与问题最相关的若干轮，原文拼接返回（空串=无命中/降级）。

    向量 + rerank 两段（跳 BM25：个人对话语料持续增长，词面索引维护不动）。
    任何异常返回 ""，不抛错——调用方直接不加回查段。
    """
    if not thread_id or not question.strip():
        return ""
    try:
        vs = _get_memory_store()
        # 向量路召回候选（tag 过滤把检索范围锁在本线程内）
        scored = vs.similarity_search_with_score(
            question, k=RECALL_POOL_K, filter=f"@tag:{{{mem_tag(thread_id)}}}"
        )
        docs = [d for d, _ in scored]
        if not docs:
            return ""
        # rerank 精排；失败退回向量顺序截断（同 kb 侧降级语义）
        reranked = retriever.rerank(question, docs, top_k)
        hits = reranked if reranked is not None else docs[:top_k]
        return "\n---\n".join(d.page_content for d in hits)
    except Exception as e:
        logger.warning(f"  → mem_43 语义回查失败（本轮不加回查段）：{e}")
        return ""
