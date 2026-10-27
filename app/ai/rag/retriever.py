"""RAG 在线检索：向量 + BM25 双路召回 → RRF 融合 → rerank 精排。

职责边界：本模块只管"查"。建库管线（分块/打 tag/幂等入库/BM25 索引）在 app/ai/rag/builder.py。

调用链路：
  启动：main.lifespan → build_graph() → builder.build_vector_store() → set_vector_store() 注入
  运行（业务节点 db/chart/email_dispatcher）：节点 → build_metric_block() → retrieve_schema()
  运行（rag 节点）：节点 → retrieve_schema(q, tag_filter="hotel")，只召回业务知识，不被口径/规范段污染
"""
import os
import threading
from datetime import date

from loguru import logger

from app.ai.rag import builder

# 检索参数
# ========
RECALL_K = 5        # 最终喂给 LLM 的段数
POOL_K = 10         # 融合前每一路各自的候选数

# 启动期由 build.py 经 set_vector_store 注入；没注入（测试场景）则首次检索时自建
_vector_store = None
_vector_store_lock = threading.Lock()


def set_vector_store(vs) -> None:
    """启动期由 build.py 注入建好的库"""
    global _vector_store
    _vector_store = vs


def _get_vector_store():
    """双检锁拿 vector_store（线程安全）"""
    global _vector_store
    if _vector_store is None:
        with _vector_store_lock:
            if _vector_store is None:  # 第二道检查：抢到锁再验一次
                _vector_store = builder.build_vector_store()
    return _vector_store


# 融合 + 精排（被 retrieve_schema 调）
# ====================================

def _rrf_fuse(vec_docs: list, bm_docs: list, k: int = 60) -> list:
    """RRF（Reciprocal Rank Fusion）：按【排名】融合两路结果，不按【分数】。

    score = Σ 1/(k+rank)。向量分（0~1）和 BM25 分（0~20+）量纲不同不能直接加权，
    按名次融合天然免疫；k=60 是论文经验值。
    去重按 page_content——两路召回同一段时应当加分（两种口径都认可它），而不是算两条。
    """
    score, keep = {}, {}
    for docs in (vec_docs, bm_docs):   # 两路名单共用同一套打分/去重逻辑
        for rank, d in enumerate(docs):
            key = d.page_content
            score[key] = score.get(key, 0) + 1.0 / (k + rank + 1)
            keep.setdefault(key, d)
    sorted_keys = sorted(score, key=score.get, reverse=True)                  # 按 RRF 累计分降序排 key
    return [keep[key] for key in sorted_keys]                                  # 用 key 去 keep 取 Document


def rerank(question: str, docs: list, top_n: int):
    """rerank 精排：候选池交给 DashScope gte-rerank-v2 重排，取 top_n。
    失败返回 None（调用方退回 RRF 顺序截断）。
    公开函数：kb 检索（本文件 retrieve_schema）与记忆回查（mem/history.mem_recall）共用。

    注意两个坑（所以直调 dashscope SDK 而不是 langchain 的 DashScopeRerank wrapper）：
      1. wrapper 的 validator 会把 model 无条件改回 gte-rerank v1（本项目 key 只有 v2 权限）；
      2. SDK 失败时不抛异常、返回 output=None 的响应，必须先查 status_code 再取结果。
    """
    if not docs:
        return None
    try:
        import dashscope
        # dashscope.TextReRank.call()：阿里 dashscope SDK 的 rerank 接口，对候选文档重排；返回 resp.output.results 拿新顺序
        resp = dashscope.TextReRank.call(
            model=os.getenv("DASHSCOPE_RERANK_MODEL", "gte-rerank-v2"),
            query=question,
            documents=[d.page_content for d in docs],
            top_n=top_n,
            return_documents=False,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
        )
        # SDK 失败不抛异常，真实错误在 code/message，先查状态码再取结果
        if resp.status_code != 200:
            logger.warning(f"rerank 失败（退回 RRF 顺序截断）：HTTP {resp.status_code} {resp.code} {resp.message}")
            return None
        # rerank 返回的是"按相关性重排后的段号列表"——拿到原 docs 里查 Document
        reranked_indices = [r.index for r in resp.output.results]                                # ① 拿新顺序的段号
        reranked_docs = [docs[i] for i in reranked_indices]                                       # ② 用段号去 docs 查 Document
        return reranked_docs
    except Exception as e:
        logger.warning(f"rerank 失败（退回 RRF 顺序截断）：{e}")
        return None


# 主流程：向量+BM25 双路召回 → RRF 融合 → rerank 精排
# ===================================================

def retrieve_schema(question: str, tag_filter: str | None = None) -> str:
    """RAG 检索：按问题召回相关语料段（business=指标口径/查询规范，hotel=业务知识）。

    管线：向量 + BM25 混合召回（各 POOL_K 条）→ RRF 融合 → rerank 精排取前 RECALL_K 段。
    降级：BM25 不可用退纯向量；rerank 失败退 RRF 顺序截断。

    tag_filter（baseMem "分支名与节点名一一对应"）：
      - "business"：业务节点（db/chart/email_dispatcher）—— 只召回指标口径/查询规范/SQL 写法
      - "hotel"：rag 节点 —— 只召回业务知识，不被口径/规范段污染
    """
    vs = _get_vector_store()
    # 向量路：多召回一些进候选池（POOL_K=10），融合后再截断
    # similarity_search_with_score()：RediSearch FLAT 暴力余弦检索，返回 [(Document, score)]，score 越小越相关
    # filter 用 RediSearch 字符串按 tag 过滤（langchain-redis 不接受 dict）
    scored = vs.similarity_search_with_score(
        question, k=POOL_K, filter=f"@tag:{{{tag_filter}}}" if tag_filter else None
    )
    vec_docs = [doc for doc, _ in scored]

    bm_docs = builder.bm25_ranked(question, POOL_K, tag=tag_filter or "")
    if bm_docs:
        candidates = _rrf_fuse(vec_docs, bm_docs)
        mode = f"混合(向量+BM25){f'/tag={tag_filter}' if tag_filter else ''}"
    else:
        candidates = vec_docs                # 降级：BM25 不可用就纯向量
        mode = f"纯向量{f'/tag={tag_filter}' if tag_filter else ''}"

    # rerank 精排；失败退回 RRF 截断。
    # 候选不超 RECALL_K 时全部都要喂给 LLM，rerank 只剩排序收益却白烧一次 HTTP，跳过
    if len(candidates) > RECALL_K:
        reranked = rerank(question, candidates, RECALL_K)
        if reranked is not None:
            docs = reranked
            mode += "+rerank"
        else:
            docs = candidates[:RECALL_K]
    else:
        docs = candidates

    schema = "\n---\n".join(d.page_content for d in docs)
    logger.info(f"  → RAG {mode} 检索到 {len(docs)} 段语料资料")
    return schema


# 节点入口：拼好"给 LLM 的资料块"
# ===============================

def build_metric_block(question: str) -> str:
    """按问题检索"指标口径 + 查询规范"，拼成给 LLM 的资料块（db/chart/email_dispatcher 共用）。

    职责是口径，不是表结构：OCC/ADR/RevPAR 公式、营收滤"已支付"、多门店汇总禁直接 AVG 等
    规则只存在于本检索的语料里——表名列名的全量字典在 sql_query 工具说明（16 表规模装得下），
    这里不重复。库表涨到字典装不下时，结构细节回本检索按问题取，管线不变。

    固定 tag_filter="business"：不召回 rag 节点的"酒店业务知识"段（tag=hotel），避免污染 SQL 生成。
    """
    material = retrieve_schema(question, tag_filter="business")
    return (
        # 日期锚点：模型不知道今天几号，裸"8月"会照着库里最大月瞎猜（库数据超前于真实日期）
        f"【今天】{date.today()}（没给年份的月份/季度 = 最近已过去的那个；\"最近N天/N月\" 以今天为终点往前推）\n"
        "【指标口径与查询规范】\n"
        f"{material}\n"
        "（完整可用表清单见 sql_query 工具说明；缺字段用 describe_table 自查，不要凭直觉造表名/列名）"
    )
