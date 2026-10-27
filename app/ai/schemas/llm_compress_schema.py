"""压缩节点的结构化输出模型（mem/compress.compress_chunk 用，轻量模型）。

与 clarify/route 同一套 with_structured_output 模式，不再手写文本标记解析。
facts 不带轮次字段——冲突消解靠 merge_facts 同 key 覆盖（后压的块天然更新），轮次无用途。
"""
from pydantic import BaseModel, Field


class CompressFact(BaseModel):
    """一条关键事实：类别 + 内容"""
    key: str = Field(description="类别：邮箱/身份/口径/指标/收件人，不属于以上填 其他")
    content: str = Field(description="事实内容，一句话")


class CompressResult(BaseModel):
    """一个对话块的压缩结果：块摘要 + 块内事实"""
    summary: str = Field(
        description="块摘要。固定格式：■ 时间段：+【结论】/【硬数据】/【待办】三段逐条一行，宁多勿漏"
    )
    facts: list[CompressFact] = Field(
        default_factory=list, description="后续作答必须记住的关键事实，没有给空表"
    )
