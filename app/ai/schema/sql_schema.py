# SQL 相关的两个结构放一起：mysql_tool 的入参 + db/chart 节点要模型输出的 SQL
from pydantic import BaseModel, Field


class MYsqlSchema(BaseModel):
    """mysql_tool 的参数结构"""
    sql: str = Field(..., description="mysql语句")


class SQLQuery(BaseModel):
    """SQL 查询结构：db/chart 节点用 with_structured_output 绑定"""
    sql: str = Field(..., description="sql查询语句，只允许 SELECT，不能有删除修改语句")
