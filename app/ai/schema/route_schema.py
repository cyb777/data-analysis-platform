# 路由结论的结构（用 with_structured_output 绑定 Pydantic）
from pydantic import BaseModel, Field


class Route(BaseModel):
    """路由结论：route 节点让模型只输出一个分支词"""
    branch: str = Field(..., description="只能是 rag / db / chart / llm 四选一")
