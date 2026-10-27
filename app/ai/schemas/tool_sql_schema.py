# sql_query_tool 的入参结构
from pydantic import BaseModel, Field


class MYsqlSchema(BaseModel):
    """sql_query_tool 的参数结构"""
    sql: str = Field(..., description="mysql语句")
