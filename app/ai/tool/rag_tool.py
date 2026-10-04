"""RAG 工具层：知识库建库 + 混合检索 + 工具包装。

职责：
  - 建库：docs/分析平台知识库.txt（表结构 + 指标口径）→ 分块 → 向量化 → Redis 入库，
    同时建一份 BM25 关键词索引（纯内存，混合检索用）。
    【启动期由 build.py 显式调一次，不在 import 时触发】
  - 检索：retrieve_schema() —— 写 SQL 前先查"这问题涉及哪些表/口径"，
    「向量 + BM25 混合召回 + RRF 融合 + rerank 精排」。
    【运行期被节点调，懒加载 + 锁，保证并发安全】
  - 工具：@tool 装饰器暴露给节点，节点只调工具，不用关心 RAG 内部细节。

调用链路：
  启动：main.lifespan → build_graph() → 显式调 build_vector_store() → vector_store 就绪
  运行（业务节点 db/chart/email_dispatcher）：节点 → build_schema_block() → retrieve_schema_with_whitelist() → retrieve_schema() → _get_vector_store() → similarity_search
  运行（rag 节点 LangChain agent）：rag 节点 → retrieve_schema_rag_tool.func()（@tool 包装对象）→ retrieve_schema()
"""
import os
import re
import threading
from pathlib import Path

from dotenv import load_dotenv
from langchain.tools import tool
from langchain_community.document_loaders import TextLoader
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_redis import RedisConfig, RedisVectorStore
from loguru import logger

from app.ai.schemas.tool_rag_schema import RAGSchema

load_dotenv()

# ====== 检索参数 ======
RECALL_K = 5        # 最终喂给 LLM 的段数
POOL_K = 10         # 融合前每一路各自的候选数

# 本项目根目录 = app/ai/tool/rag_tool 往上 3 层（tool → ai → app → 项目根）
BASE_DIR = Path(__file__).resolve().parents[3]
DOC_PATH = BASE_DIR / "docs" / "分析平台知识库.txt"

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# embedding——把文字变成向量，才能比较"像不像"
emb = DashScopeEmbeddings(
    model=os.getenv("DASHSCOPE_MODEL_NAME", "text-embedding-v4"),
    dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
)


# ====== 叶子函数：被 _build_bm25 和 _bm25_ranked 共用 ======

def _tokenize(s: str) -> list[str]:
    """分词：中文用 jieba，英文标识符额外拆一遍。
    pay_type → ['pay_type', 'pay', 'type']，
    这样用户问「支付类型」（jieba 切出中文词）和问「pay_type」都能命中同一段。
    """
    import jieba
    # jieba.lcut：jieba 中文分词的"切一刀"函数，传入中文句子返回词语列表；
    # 它不认识英文标识符（如 pay_type），所以下面用正则再补一刀抓英文
    # ① jieba 把句子切成词列表；      
    cut_words = jieba.lcut(s)   
    #② 过滤空 token； 统一小写、去首尾空格                                                   
    toks = [w.strip().lower() for w in cut_words if w.strip()]
        
    for ident in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", s):
        low = ident.lower()
        toks.append(low)
        toks.extend(p for p in low.split("_") if p)
    return toks


# ====== 启动期：建库 + 建 BM25 索引 ======

def _build_bm25(chunks: list[str]) -> None:
    """建 BM25 索引（建库时顺手调一次，纯内存、无网络、耗时可忽略）。
    失败不抛异常——BM25 只是增强项，挂了退回纯向量照样能跑。
    """
    global _bm25, _bm25_chunks
    try:
        from rank_bm25 import BM25Okapi
        _bm25_chunks = chunks
        # BM25Okapi：经典 BM25 关键词打分算法；传入"每段的分词列表"建索引，检索时给每段打分
        # 内部数据结构示意（伪代码）：倒排索引 = {词: [(段号, tf, doc_len), ...]}
        #   "销售额" → [
        #       (段1, tf=3, doc_len=280),    # 在段1出现3次，段1长280字
        #       (段5, tf=1, doc_len=200),    # 在段5出现1次，段5长200字
        #       (段9, tf=2, doc_len=320),    # 在段9出现2次，段9长320字
        #   ]
        _bm25 = BM25Okapi([_tokenize(c) for c in chunks])
        logger.info(f"BM25 关键词索引建成：{len(chunks)} 段")
    except Exception as e:
        _bm25, _bm25_chunks = None, []
        logger.warning(f"BM25 索引建立失败（不影响主流程，退回纯向量检索）：{e}")


# BM25 全局状态：_bm25_ranked 要读，_build_bm25 要写
_bm25 = None            # BM25Okapi 实例
_bm25_chunks = []       # 和 _bm25 一一对应的原文分块（融合时要还原成 Document）


def build_vector_store():
    """加载知识库文档 → 分块（按章节打 tag）→ 向量化 → Redis 入库（启动期显式调 1 次）

    ⚠️ 由 build.py 在编排图之前显式调一次；不放在 import 时自动执行——
    否则任何 import 本模块的地方（单测、工具脚本）都要付一次 embedding 调用 + Redis 连接。

    tag 设计（baseMem L138 "分支名与节点名一一对应"）：
      - schema / sql_pattern / spec：业务节点（db/chart）走
      - definition：rag 节点走（业务口径专业问题）
    """
    loader = TextLoader(DOC_PATH, encoding="utf-8")
    # TextLoader.load()：读 .txt 文件返回 [Document]，Document.page_content 是正文
    text = loader.load()[0].page_content

    # 按章节切（MarkdownTextSplitter 认 ## 标题），每章一个 chunk + 一个 tag
    # tag 识别规则（v1.5.6 精简到 2 类）：
    #   "一、表结构说明" / "二、指标口径" / "三、查询规范" → business
    #   "四、RAG 节点专用召回" → hotel
    from langchain_text_splitters import MarkdownTextSplitter
    splitter = MarkdownTextSplitter(chunk_size=600, chunk_overlap=120)
    docs = splitter.create_documents([text])
    # 给每个 chunk 打 tag：根据 chunk 第一行 "## " 标题判断章节
    tag_by_section = {
        "一、表结构说明": "business",
        "二、指标口径": "business",
        "三、查询规范": "business",
        "四、RAG 节点专用召回": "hotel",
    }
    section_tag = "business"  # 默认（文档头部"〇、表范围"段）
    chunk_texts = []
    chunk_metas = []
    for d in docs:
        # 每段第一行可能是 "## 标题"，识别出来后切换 section_tag
        first_line = d.page_content.split("\n", 1)[0].strip()
        for title, tag in tag_by_section.items():
            if first_line.startswith(f"## {title}") or first_line.startswith(title):
                section_tag = tag
                break
        chunk_texts.append(d.page_content)
        chunk_metas.append({"tag": section_tag})
    chunks = chunk_texts
    logger.info(f"知识库分块完成：{len(chunks)} 段（按章节打 tag）")

    # 同一批 chunks 顺手建一份 BM25 关键词索引（混合检索用，见 _bm25_ranked）
    _build_bm25(chunks)

    # 向量化 + Redis 入库，add_texts 一步完成（带 metadata）
    # v1.5.6：显式声明 index_schema，把 metadata['tag'] 建为 RediSearch TAG 字段才能按 tag 过滤
    # langchain-redis 0.5.2 不展开 metadata 成 schema 字段，必须显式声明；否则 @tag:{xxx} 报 Unknown field
    from redisvl.schema import IndexSchema, TagField, TextField, FlatVectorField, IndexInfo
    from redisvl.schema.fields import FlatVectorFieldAttributes
    # embedding 维度从 embedding 模型对象拿（dashscope text-embedding-v4 / qwen3.7 都是 1024）
    schema = IndexSchema(
        index=IndexInfo(name="kb_43", prefix="kb_43", storage_type="hash"),
        fields={
            "tag": TagField(name="tag"),
            "text": TextField(name="text"),
            "embedding": FlatVectorField(
                name="embedding",
                attrs=FlatVectorFieldAttributes(dims=1024, distance_metric="COSINE"),
            ),
        },
    )
    config = RedisConfig(
        index_name="kb_43",
        redis_url=f"redis://{REDIS_HOST}:{REDIS_PORT}",
        distance_metric="COSINE",
        index_schema=schema,
    )
    vs = RedisVectorStore(embeddings=emb, config=config)
    # add_texts：langchain_redis 的"一步入库"——内部自动做 embedding、调 Redis 写向量+元数据、建 FAISS 索引
    # qwen3.7-text-embedding-flash 单批 ≤ 20 段（DashScope API 限制），按 20 段切片循环入库
    BATCH_SIZE = 20
    for i in range(0, len(chunks), BATCH_SIZE):
        vs.add_texts(chunks[i:i + BATCH_SIZE], metadatas=chunk_metas[i:i + BATCH_SIZE])
    logger.info(f"向量库构建完成（索引 kb_43，RedisVectorStore 内部用 FAISS 存向量，Redis 只存元数据；{len(set(m['tag'] for m in chunk_metas))} 个 tag）")
    return vs


# ====== 运行期：懒加载 + 双检锁拿库 ======
# build.py 启动期显式填好；没填（测试场景）则首次检索时自建
_vector_store = None
_vector_store_lock = threading.Lock()


def _get_vector_store():
    """双检锁拿 vector_store（线程安全）"""
    global _vector_store
    if _vector_store is None:
        with _vector_store_lock:
            if _vector_store is None:  # 第二道检查：抢到锁再验一次
                _vector_store = build_vector_store()
    return _vector_store


# ====== 运行期：BM25 召回（被 retrieve_schema 调） ======

def _bm25_ranked(question: str, top_k: int):
    """BM25 召回 top_k 段，包装成 Document 以便和向量结果统一融合。
    返回空列表 = BM25 不可用，调用方自动降级。
    """
    if _bm25 is None:
        return []
    try:
        from langchain_core.documents import Document
        scores = _bm25.get_scores(_tokenize(question))
        # get_scores()：BM25 给知识库每段打一个相关性分（数越大越相关），下面按分排序取 top_k
        # 先拿段号列表，再按 scores 排序，最后截前 top_k
        all_indices = range(len(_bm25_chunks))                                              # ① 所有段号 [0,1,2,...,n-1]
        ranked_indices = sorted(all_indices, key=lambda i: scores[i], reverse=True)        # ② 按 scores[i] 降序排段号
        order = ranked_indices[:top_k]                                                     # ③ 截前 top_k 个段号
        bm25_docs = [Document(page_content=_bm25_chunks[i]) for i in order]                  # ④ 用段号去 chunks 还原 Document
        return bm25_docs
    except Exception as e:
        logger.warning(f"BM25 检索失败（退回纯向量）：{e}")
        return []


# ====== 运行期：融合 + 精排（被 retrieve_schema 调） ======

def _rrf_fuse(vec_docs: list, bm_docs: list, k: int = 60) -> list:
    """RRF（Reciprocal Rank Fusion）：按【排名】融合两路结果，不按【分数】。

    score = Σ 1/(k+rank)。向量分（0~1）和 BM25 分（0~20+）量纲不同不能直接加权，
    按名次融合天然免疫；k=60 是论文经验值。
    去重按 page_content——两路召回同一段时应当加分（两种口径都认可它），而不是算两条。
    """
    score, keep = {}, {}
    for rank, d in enumerate(vec_docs):
        key = d.page_content
        score[key] = score.get(key, 0) + 1.0 / (k + rank + 1)
        keep.setdefault(key, d)
    for rank, d in enumerate(bm_docs):
        key = d.page_content
        score[key] = score.get(key, 0) + 1.0 / (k + rank + 1)
        keep.setdefault(key, d)
    sorted_keys = sorted(score, key=score.get, reverse=True)                  # 按 RRF 累计分降序排 key
    fused_docs = [keep[key] for key in sorted_keys]                            # 用 key 去 keep 取 Document
    return fused_docs


def _rerank(question: str, docs: list, top_n: int):
    """rerank 精排：候选池交给 DashScope gte-rerank-v2 重排，取 top_n。
    失败返回 None（调用方退回 RRF 顺序截断）。

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


# ====== 主流程：向量+BM25 双路召回 → RRF 融合 → rerank 精排 ======

def retrieve_schema(question: str, tag_filter: str | None = None) -> str:
    """RAG 检索：这个问题涉及哪些表 / 指标口径。

    管线：向量 + BM25 混合召回（各 POOL_K 条）→ RRF 融合 → rerank 精排取前 RECALL_K 段。
    降级：BM25 不可用退纯向量；rerank 失败退 RRF 顺序截断。

    tag_filter（baseMem L138 "分支名与节点名一一对应"）：
      - None / "schema"：业务节点（db/chart）—— 召回表结构/SQL 模式/规范
      - "definition"：rag 节点 —— 只召回业务口径定义，不被表结构污染
    """
    vs = _get_vector_store()
    # 向量路：多召回一些进候选池（POOL_K=10），融合后再截断
    # similarity_search_with_score()：FAISS 向量相似度检索，返回 [(Document, score)] 列表，score 越小越相关（COSINE 距离）
    # tag_filter 参数传给底层 RediSearch，让 Redis 按 tag 过滤召回的段
    # langchain-redis 0.5.2 要求 filter_expression 是 FilterExpression 对象或 RediSearch 字符串（langchain-redis 不接受 dict）
    scored = vs.similarity_search_with_score(
        question, k=POOL_K, filter=f"@tag:{{{tag_filter}}}" if tag_filter else None
    )
    vec_docs = [doc for doc, _ in scored]

    bm_docs = _bm25_ranked(question, POOL_K)
    if bm_docs:
        candidates = _rrf_fuse(vec_docs, bm_docs)
        mode = f"混合(向量+BM25){f'/tag={tag_filter}' if tag_filter else ''}"
    else:
        candidates = vec_docs                # 降级：BM25 不可用就纯向量
        mode = f"纯向量{f'/tag={tag_filter}' if tag_filter else ''}"

    # rerank 精排；失败退回 RRF 截断
    reranked = _rerank(question, candidates, RECALL_K)
    if reranked is not None:
        docs = reranked
        mode += "+rerank"
    else:
        docs = candidates[:RECALL_K]

    schema = "\n---\n".join(d.page_content for d in docs)
    logger.info(f"  → RAG {mode} 检索到 {len(docs)} 段表结构/口径资料")
    return schema


# ====== 辅助：解析列名白名单（被 retrieve_schema_with_whitelist 调） ======

def _extract_columns(schema_text: str) -> str:
    """从 RAG 资料里提取"表名: 列名1, 列名2"清单。
    知识库每条字段长这样：'- user_id：客户ID（主键）' 或 '- username：客户名'
    我们要抓的是 '-' 开头、'：' 前的那串字符（列名）。
    """
    table_col_map: dict[str, list[str]] = {}
    current_table = None
    for line in schema_text.splitlines():
        # 匹配 "### N. customer 客户表" 之类的表头
        m_table = re.match(r"###\s*\d+\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\s", line)
        if m_table:
            current_table = m_table.group(1)
            table_col_map.setdefault(current_table, [])
            continue
        # 匹配 "- 列名：" 形式的字段
        if current_table:
            m_col = re.match(r"\s*-\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[:：]", line)
            if m_col:
                col = m_col.group(1)
                if col not in table_col_map[current_table]:
                    table_col_map[current_table].append(col)
    if not table_col_map:
        return "（本次没解析出列名）"
    lines = [f"- {tbl}: {', '.join(cols)}" for tbl, cols in table_col_map.items()]  # 每行拼成 "- 表名: 列1, 列2"
    whitelist = "\n".join(lines)                                                     # 用换行拼成一个字符串
    return whitelist


# ====== 主流程外壳：+列名白名单（被 build_schema_block 调） ======

def retrieve_schema_with_whitelist(question: str, tag_filter: str | None = None) -> tuple[str, str]:
    """RAG 检索 + 列名白名单提取。
    返回 (schema_text, column_whitelist)：
      - schema_text：RAG 原文（给 LLM 看的"业务口径"）
      - column_whitelist：解析出来的"表名: 列1, 列2, ..."清单（给 LLM 明确的列名边界）

    tag_filter（v1.5.7）：业务节点传 "business"，rag 节点传 "hotel"。
    """
    schema = retrieve_schema(question, tag_filter=tag_filter)
    whitelist = _extract_columns(schema)
    return schema, whitelist


# ====== 节点入口：拼好"给 LLM 的资料块" ======

def build_schema_block(question: str) -> tuple[str, str]:
    """RAG 检索 + 拼好"给 LLM 的资料块"（chart/db 节点共用，避免两处重复写措辞）

    返回 (schema_text, schema_block)：
      - schema_text：RAG 原文（节点在失败分支里单独用）
      - schema_block：白名单 + 原文拼好的完整文本，直接塞进消息
    ⚠️ 措辞要点：白名单只说"仅供参考，可能不完整"，绝不说"必须从白名单里选"——
    否则 LLM 缺表时会被逼着在残缺清单里硬凑表名。缺表让它用 describe_table 自查。

    v1.5.7 业务节点显式传 tag_filter="business" —— 只召回业务辅助段（表结构/指标口径/查询规范），
    不召回 rag 节点的"酒店业务知识"段（tag=hotel），避免酒店业务知识段污染 SQL 生成。
    """
    schema, whitelist = retrieve_schema_with_whitelist(question, tag_filter="business")
    block = (
        "【本次召回到的相关列名（仅供参考，可能不完整）】\n"
        f"{whitelist}\n"
        "（完整可用表清单见 sql_query 工具说明；上面没有的表用 describe_table 自查，不要凭直觉造表名/列名）\n\n"
        "【表结构/业务口径资料】\n"
        f"{schema}"
    )
    return schema, block


# ====== LangChain 工具包装（独立支，节点代码只需 from app.ai.tool.rag_tool import retrieve_schema_rag_tool 等） ======

@tool("retrieve_schema", args_schema=RAGSchema)
# @tool：LangChain 工具装饰器，把普通函数包成 StructuredTool 对象，LLM 才能识别+调用；args_schema 告诉 LLM 参数长啥样
def retrieve_schema_rag_tool(question: str) -> str:
    """RAG 检索：根据用户问题，从向量库召回相关表结构/业务口径资料。
    失败时降级为兜底（让 LLM 自行用 describe_table 工具自查）。

    ⚠️ 只供 rag 节点 .func() 调用（rag 节点是 LangChain agent，要拿 @tool 包装的对象）；
    其他业务节点（db/chart/email_dispatcher）调 build_schema_block（直接拿拼好的资料块，不走 langchain 工具链）。

    tag 过滤（v1.5.7：2 类 tag，rag 节点只召回业务知识段）：
      - 业务节点（db/chart）传 tag_filter="business" → 只召回业务辅助段
      - rag 节点传 tag_filter="hotel" → 只召回酒店业务口径定义段
    """
    try:
        return retrieve_schema(question, tag_filter="hotel")
    except Exception as e:
        logger.warning("RAG 检索失败，降级为兜底：{}", e)
        return "（RAG 检索降级：暂无表结构资料，请用 describe_table 工具自查）"


# ====== 显式 __all__：节点代码只需 from app.ai.tool.rag_tool import retrieve_schema 等 ======
# 函数本体（不是 @tool 包装后的对象）直接通过模块属性访问
__all__ = [
    "build_vector_store",                # 建库（启动期 build.py 显式调）
    "retrieve_schema",                   # RAG 检索函数本体
    "retrieve_schema_with_whitelist",    # RAG 检索 + 列名白名单
    "build_schema_block",                # RAG 检索 + 拼好资料块（chart/db 节点用）
    "_extract_columns",                  # 列名提取（内部辅助）
    "retrieve_schema_rag_tool",        # @tool 包装（只供 rag 节点 .func() 调用）
]