# 反问澄清结论的结构（with_structured_output 绑定 Pydantic）
from pydantic import BaseModel, Field


class ClarifyGuess(BaseModel):
    """clarify 节点的反问结论：猜用户到底想问什么，并给出可点选的候选问题。

    用 with_structured_output 强制模型只吐这个结构——自由文本里混进解释、编号、
    Markdown 会让前端的选项按钮渲染错乱（route 的 Route 同款做法）。
    """
    missing_tip: str = Field(
        ...,
        description="一句反问，直接对用户说（如「你是想对比哪几家店？」），给用户看",
    )
    options: list[str] = Field(
        ...,
        description=(
            "2-4 个候选问题，供用户点选：每个都要具体、可直接执行（带指标/时间/门店口径），"
            "彼此方向不同，且不要与上一轮已经答过的内容重复"
        ),
    )
