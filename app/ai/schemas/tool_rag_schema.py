"""RAG 工具入参结构"""
from pydantic import BaseModel, Field


class RAGSchema(BaseModel):
    """RAG 工具的参数：用户问题 + 可选 force_rebuild（建库用）"""
    question: str = Field(..., description="用户问题/查询文本")
    force_rebuild: bool = Field(default=False, description="是否强制重建向量库（仅 build_vector_store 用）")
