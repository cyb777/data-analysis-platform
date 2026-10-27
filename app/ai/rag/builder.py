"""RAG 建库管线：知识库文档 → 分块打 tag → 幂等/增量写入 Redis 向量库 + 内存 BM25 索引。

职责边界：本模块只管"建"，在线检索（召回/融合/精排）在 app/ai/rag/retriever.py。
启动期由 build.py 显式调一次 build_vector_store()，不在 import 时触发——
否则任何 import 本模块的地方（单测、工具脚本）都要付一次 embedding 调用 + Redis 连接。

幂等与增量：
  - 确定性 key：key = f"kb_43:{sha1(chunk文本)[:16]}"，同内容重复 add 覆盖同一 Redis hash，重启不翻倍；
  - manifest（rag_corpus/.manifest.json）记录 {文件名: {sha256, chunk_keys}}，启动时逐文件比对：
    未变 → 跳过（0 次 embedding 调用、0 次写库）；变更/新增 → 旧 chunk_keys 先删再写；
    manifest 里有、目录里没了 → 删残留 chunk_keys。
  - BM25 是纯内存索引，每次启动都全量重建（无网络、耗时可忽略），不受增量跳过影响。
"""
import hashlib
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_community.document_loaders import TextLoader
from langchain_community.embeddings import DashScopeEmbeddings
from loguru import logger

load_dotenv()

# 本项目根目录 = app/ai/rag/builder.py 往上 3 层（rag → ai → app → 项目根）
BASE_DIR = Path(__file__).resolve().parents[3]
KB_DIR = BASE_DIR / "rag_corpus"                   # RAG 语料目录（项目根下，读取其中全部 .md/.txt）
MANIFEST_PATH = KB_DIR / ".manifest.json"          # 增量构建台账
INDEX_NAME = "kb_43"                               # RediSearch 索引名（schema 前缀与 chunk key 前缀共用）
BATCH_SIZE = 20                                    # DashScope embedding 每批上限 20 段

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
# embedding——把文字变成向量，才能比较"像不像"
emb = DashScopeEmbeddings(
    model=os.getenv("DASHSCOPE_MODEL_NAME", "text-embedding-v4"),
    dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
)


# 分词：被 _build_bm25 和 bm25_ranked 共用
# ========================================

def _tokenize(s: str) -> list[str]:
    """分词：中文用 jieba，英文标识符额外拆一遍。
    pay_type → ['pay_type', 'pay', 'type']，
    这样用户问「支付类型」（jieba 切出中文词）和问「pay_type」都能命中同一段。
    """
    import jieba
    # jieba.lcut：jieba 中文分词函数；它不认识英文标识符（如 pay_type），所以下面用正则再补一刀
    cut_words = jieba.lcut(s)
    toks = [w.strip().lower() for w in cut_words if w.strip()]
    for ident in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", s):
        low = ident.lower()
        toks.append(low)
        toks.extend(p for p in low.split("_") if p)
    return toks


# 文件级 tag 登记（检索时 db/chart 看 business、rag 看 hotel）
# ============================================================
# tag 判定只有一条规则：查 rag_corpus/tags.json 登记表，没登记的文件默认 hotel。
# 默认归 hotel 的方向考量：business 语料就指标口径与查询模板一本（固定，登记一次完事），
# 业务知识会持续扩充（新增免登记）；漏登记的新文件只进 hotel（rag 多召回一段），
# 不会反向污染 SQL 召回。一个文件一个主题、整篇一个 tag——不在文件内做章节级判定
# （切分不保证章节标题落在段首，章节覆盖规则曾把整本 SQL 口径错挂成 hotel）。
def _load_file_tags() -> dict:
    """读语料目录的 tags.json（{文件名: tag}）；没有或损坏返回空表（全部走默认 hotel）。
    缺失/损坏必须打 warning：此时 business 类文件会被静默错挂成 hotel，
    db/chart 将召不到 SQL 口径——不能无声失败。
    """
    tags_path = KB_DIR / "tags.json"
    if not tags_path.exists():
        logger.warning(f"tags.json 不存在（{tags_path}），全部语料默认 hotel，business 类文件将被错挂")
        return {}
    try:
        # utf-8-sig：Windows 记事本保存常带 BOM，json.loads 遇 BOM 直接报错
        return json.loads(tags_path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        logger.warning(f"tags.json 解析失败（{e}），全部语料默认 hotel，business 类文件将被错挂")
        return {}


def _split_and_tag(path: Path, file_tags: dict) -> tuple[list[str], list[dict]]:
    """读一个知识库文件 → MarkdownTextSplitter 分块 → 按 tags.json 登记打文件级 tag（未登记默认 hotel）。
    file_tags 由调用方一次性 _load_file_tags() 传入——不在本函数内逐文件重读
    tags.json（否则 N 文件 = N 次磁盘 IO + JSON 解析）。
    返回 (chunk_texts, chunk_metas)，两列表等长同序。
    """
    text = TextLoader(str(path), encoding="utf-8").load()[0].page_content
    from langchain_text_splitters import MarkdownTextSplitter
    splitter = MarkdownTextSplitter(chunk_size=600, chunk_overlap=120)
    docs = splitter.create_documents([text])

    tag = file_tags.get(path.name, "hotel")
    chunk_texts = [d.page_content for d in docs]
    chunk_metas = [{"tag": tag} for _ in docs]
    return chunk_texts, chunk_metas


def _chunk_key(chunk_text: str) -> str:
    """chunk 的确定性 Redis key：同内容同 key，重复 add 覆盖同一 hash，重启不翻倍"""
    return f"{INDEX_NAME}:{hashlib.sha1(chunk_text.encode('utf-8')).hexdigest()[:16]}"


# manifest 台账读写
# =================

def _load_manifest() -> dict:
    """读增量台账；没有/损坏都按空台账处理（会触发全量重建，不丢正确性）"""
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(manifest: dict) -> None:
    """写增量台账"""
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


# Redis 索引状态
# ==============

def _index_doc_count() -> int | None:
    """查 RediSearch 索引文档数；索引不存在返回 None"""
    import redis
    try:
        info = redis.Redis(host=REDIS_HOST, port=REDIS_PORT).ft(INDEX_NAME).info()
        return int(info.get("num_docs", 0))
    except Exception:
        return None


def _drop_index() -> None:
    """连文档一起删索引（DD）——清旧版非确定性 key 的重复段用"""
    import redis
    try:
        redis.Redis(host=REDIS_HOST, port=REDIS_PORT).execute_command("FT.DROPINDEX", INDEX_NAME, "DD")
        logger.warning(f"已清空旧索引 {INDEX_NAME}（旧数据是非确定性 key 的重复段，本次重建后自愈）")
    except Exception as e:
        logger.warning(f"删旧索引失败（继续重建）：{e}")


def add_texts_batched(vs, texts: list[str], metas: list[dict], keys: list[str]) -> None:
    """按 BATCH_SIZE 分批写库（DashScope embedding 每批上限 20 段）。
    metadatas/keys 与 texts 等长同序：第 i 段配第 i 个 tag、第 i 个 key。
    kb_43 建库（本文件 build_vector_store）与 mem_43 入库（mem/history.embed_turns）共用。
    """
    for i in range(0, len(texts), BATCH_SIZE):
        vs.add_texts(
            texts[i:i + BATCH_SIZE],
            metadatas=metas[i:i + BATCH_SIZE],
            keys=keys[i:i + BATCH_SIZE],
        )


def _delete_chunk_keys(vs, keys: list[str]) -> None:
    """删除一批 chunk（文件变更/删除时清旧段）；失败仅告警不阻塞"""
    if not keys:
        return
    try:
        vs.delete(ids=keys)
    except Exception as e:
        logger.warning(f"删除旧 chunk 失败（{len(keys)} 条，可能残留重复段，全量重建时自愈）：{e}")


def make_vector_store(index_name: str = INDEX_NAME):
    """声明 RediSearch schema（tag 可过滤的前提）并返回 RedisVectorStore 实例。
    langchain-redis 不会自动展开 metadata，必须手写 schema。
    index_name 参数化：kb_43（知识库）与 mem_43（对话记忆，见 mem/history.py）共用同一条 schema 管线。
    """
    from langchain_redis import RedisConfig, RedisVectorStore
    from redisvl.schema import IndexSchema, TagField, TextField, FlatVectorField, IndexInfo
    from redisvl.schema.fields import FlatVectorFieldAttributes
    schema = IndexSchema(
        index=IndexInfo(name=index_name, prefix=index_name, storage_type="hash"),
        fields={
            # TagField：结构化枚举值（business / hotel / mem:*）精确过滤，走倒排索引，和 TextField 全文分词不同
            "tag": TagField(name="tag"),
            "text": TextField(name="text"),
            # FlatVectorField：1024 维（DashScope embedding 输出），COSINE 余弦距离
            "embedding": FlatVectorField(
                name="embedding",
                attrs=FlatVectorFieldAttributes(dims=1024, distance_metric="COSINE"),
            ),
        },
    )
    config = RedisConfig(
        index_name=index_name,
        redis_url=f"redis://{REDIS_HOST}:{REDIS_PORT}",
        distance_metric="COSINE",
        index_schema=schema,
    )
    return RedisVectorStore(embeddings=emb, config=config)


# BM25（纯内存，检索侧经 bm25_ranked 调用）
# =========================================
_bm25 = None            # BM25Okapi 实例
_bm25_chunks = []       # 和 _bm25 一一对应的原文分块（融合时要还原成 Document）
_bm25_tags = []         # 每块的 tag（business/hotel），检索侧按 tag 过滤、与向量路 @tag 对齐


def _build_bm25(chunks: list[str], tags: list[str] = None) -> None:
    """建 BM25 索引（每次启动全量重建，纯内存、无网络、耗时可忽略）。
    失败不抛异常——BM25 只是增强项，挂了退回纯向量照样能跑。
    """
    global _bm25, _bm25_chunks, _bm25_tags
    try:
        from rank_bm25 import BM25Okapi
        _bm25_chunks = chunks
        _bm25_tags = tags if tags and len(tags) == len(chunks) else [""] * len(chunks)
        # BM25Okapi：经典 BM25 关键词打分算法；传入"每段的分词列表"建索引，检索时给每段打分
        _bm25 = BM25Okapi([_tokenize(c) for c in chunks])
        logger.info(f"BM25 关键词索引建成：{len(chunks)} 段")
    except Exception as e:
        _bm25, _bm25_chunks, _bm25_tags = None, [], []
        logger.warning(f"BM25 索引建立失败（不影响主流程，退回纯向量检索）：{e}")


def bm25_ranked(question: str, top_k: int, tag: str = ""):
    """BM25 召回 top_k 段，包装成 Document 供检索侧 RRF 融合。
    返回空列表 = BM25 不可用，调用方自动降级纯向量。
    tag 给定时只召该 tag 的段——与向量路 @tag 过滤同口径：
    不过滤的话异 tag 段会经 RRF 混进结果，business/hotel 两类语料隔离就失效了。
    """
    if _bm25 is None:
        return []
    try:
        from langchain_core.documents import Document
        scores = _bm25.get_scores(_tokenize(question))
        # get_scores()：给知识库每段打一个相关性分（越大越相关）；先按 tag 筛下标再按分降序截前 top_k
        idxs = [i for i in range(len(_bm25_chunks)) if not tag or _bm25_tags[i] == tag]
        order = sorted(idxs, key=lambda i: scores[i], reverse=True)[:top_k]
        return [Document(page_content=_bm25_chunks[i]) for i in order]
    except Exception as e:
        logger.warning(f"BM25 检索失败（退回纯向量）：{e}")
        return []


# 建库入口
# ========

def build_vector_store():
    """建库入口（启动期 build.py 显式调 1 次）：多文档扫描 → 增量/幂等写 Redis → 全量重建 BM25"""
    kb_files = sorted([*KB_DIR.glob("*.md"), *KB_DIR.glob("*.txt")])
    if not kb_files:
        raise FileNotFoundError(f"知识库目录 {KB_DIR} 下没有 .md/.txt 文件")

    # ① 逐文件扫描：读 → 分块 → 打 tag → 算哈希（纯本地，无 embedding）
    # =================================================================
    old_manifest = _load_manifest()
    file_tags = _load_file_tags()     # tags.json 循环外一次读入，逐文件传参
    scanned = []          # (文件名, sha256, chunks, metas, keys)
    all_chunks: list[str] = []
    all_tags: list[str] = []      # 与 all_chunks 平行：每块 tag 供 BM25 检索侧过滤
    for path in kb_files:
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        chunks, metas = _split_and_tag(path, file_tags)
        keys = [_chunk_key(c) for c in chunks]
        scanned.append((path.name, file_hash, chunks, metas, keys))
        all_chunks.extend(chunks)
        all_tags.extend(m.get("tag", "") for m in metas)

    # ② 索引状态判定
    # ==============
    doc_count = _index_doc_count()
    if doc_count and not old_manifest:
        _drop_index()     # 有数据但没台账 = 旧版 uuid 键的重复段，清一次重建
        doc_count = None
    # 索引不存在 / 索引是空的（如 Redis 被清空但台账还在）→ 全量重嵌，否则库是空的
    force_all = not doc_count

    # ③ 逐文件定计划：未变跳过 / 变更先删后写 / 新增直接写
    # ====================================================
    new_manifest: dict = {}
    to_embed: list[tuple[list[str], list[dict], list[str]]] = []
    to_delete: list[str] = []
    for name, file_hash, chunks, metas, keys in scanned:
        new_manifest[name] = {"sha256": file_hash, "chunk_keys": keys}
        old = old_manifest.get(name)
        if force_all or old is None:
            to_embed.append((chunks, metas, keys))
            if not force_all:
                logger.info(f"知识库文件 {name} 新增：{len(chunks)} 段待嵌入")
        elif old.get("sha256") != file_hash:
            to_delete.extend(old.get("chunk_keys", []))
            to_embed.append((chunks, metas, keys))
            logger.info(f"知识库文件 {name} 变更：{len(chunks)} 段待嵌入（旧段先删）")
        # else 未变 → 跳过（0 次 embedding 调用、0 次写库）
    if not force_all:
        # manifest 里有、目录里没了的文件 → 删残留段
        for gone in set(old_manifest) - {name for name, *_ in scanned}:
            dead_keys = old_manifest[gone].get("chunk_keys", [])
            to_delete.extend(dead_keys)
            logger.info(f"知识库文件 {gone} 已移除，清理其 {len(dead_keys)} 段残留")

    # ④ 建 BM25（全量、纯内存，不受增量跳过影响）
    # ===========================================
    _build_bm25(all_chunks, all_tags)

    # ⑤ 删旧段 + 嵌入新段（带确定性 keys，重复 add 覆盖同 hash）
    # ==========================================================
    vs = make_vector_store()
    _delete_chunk_keys(vs, to_delete)
    embedded = 0
    for chunks, metas, keys in to_embed:
        add_texts_batched(vs, chunks, metas, keys)
        embedded += len(chunks)
    _save_manifest(new_manifest)
    logger.info(
        f"向量库就绪（索引 {INDEX_NAME}，共 {len(all_chunks)} 段："
        f"新嵌入 {embedded} / 跳过 {len(all_chunks) - embedded} / 清理旧段 {len(to_delete)}）"
    )
    return vs
