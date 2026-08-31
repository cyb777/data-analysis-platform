"""RAG 知识库层

建库：docs/分析平台知识库.txt（表结构 + 指标口径）→ 分块 → 向量化 → Redis 入库
检索：retrieve_schema() —— 写 SQL 前先查"这问题涉及哪些表/口径"，替代硬编码 schema
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from langchain_community.document_loaders import TextLoader
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_redis import RedisConfig, RedisVectorStore

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[3]
DOC_PATH = BASE_DIR / "docs" / "分析平台知识库.txt"

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
emb = DashScopeEmbeddings(
    model="text-embedding-v4",
    dashscope_api_key=os.getenv("OPENAI_API_KEY"),
)


def build_vector_store():
    """加载知识库文档 → 分块 → 向量化 → Redis 入库（只执行一次）"""
    loader = TextLoader(DOC_PATH, encoding="utf-8")
    text = loader.load()[0].page_content

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300, chunk_overlap=60,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )
    chunks = splitter.split_text(text)
    logger.info(f"知识库分块完成：{len(chunks)} 段")

    # 向量化并写入 Redis 向量库
    config = RedisConfig(
        index_name="kb_43",
        redis_url=f"redis://{REDIS_HOST}:{REDIS_PORT}",
        distance_metric="COSINE",
    )
    vs = RedisVectorStore(embeddings=emb, config=config)
    vs.add_texts(chunks)
    logger.info(f"向量库入库完成（索引 kb_43）")
    return vs


# import 时建库（只跑一次；Redis 没启动会在这里报错）
vector_store = build_vector_store()


def retrieve_schema(question: str) -> str:
    """相似度检索：返回与问题最相关的 k=3 段表结构/口径资料"""
    results = vector_store.similarity_search_with_score(question, k=3)
    schema = "\n---\n".join(doc.page_content for doc, _ in results)
    logger.info(f"  → RAG 检索到 {len(results)} 段表结构/口径资料")
    return schema
