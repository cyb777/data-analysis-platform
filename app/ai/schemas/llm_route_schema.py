# 路由结论的结构（用 with_structured_output 绑定 Pydantic）
from typing import Literal

from pydantic import BaseModel, Field


class Route(BaseModel):
    """路由结论：route 节点让模型只输出一个分支词

    用 Literal 而不是 str：Literal 会在发给模型的 schema 里生成 enum 约束，
    API 层面强制多选一（str 只约束"是字符串"，"think"/"name_1" 这类脏值也能通过校验）。

    分支说明（对比分析改走 chart，由 chart 出分组/多系列图）：
      - clarify：问题模糊到连「要查什么」都判断不出、对话历史里也找不到上下文时才反问（极少用；
        仅缺时间范围不算 clarify——db/chart 的 SQL 智能体在没指定时间时按默认口径（最近30天）查，不反问）
      - system：发邮件/通知/提醒/催办类，要调 EmailDispatcher 调度器查数据→写正文→发出去
    """
    # 意图分类：限定 6 个分支
    #   db      → 数据查询/统计（取数节点）
    #   chart   → 图表/可视化/对比分析（对比类问题由 chart 出分组/多系列图）
    branch: Literal["rag", "db", "chart", "clarify", "system", "chat"] = Field(
        ...,
        description=(
            "按问题语义选择分支："
            "rag=业务口径/定义，"
            "db=单纯查数据，"
            "chart=画图可视化/对比分析（对比类问题由 chart 出分组/多系列图，含想看图表的表述），"
            "clarify=需要反问澄清（问题模糊到连要查什么都不知道、且历史也推断不出时才用；仅缺时间范围不要反问），"
            "system=发邮件/通知/提醒/催办类（要调 EmailDispatcher 调度器查数据→写正文→发出去），"
            "chat=普通聊天、总结、以及其他问题（不取数，直接对话回答）"
        )
    )
    # 入口改写（query rewriting）：多轮追问（"详细一点""那个呢"）离开历史无法理解，
    # route 反正已经拿着历史在调模型，同一次调用顺手改写成自包含问题，
    # 下游 db/chart/writer/chat 拿到的就是完整问题，不需要各自再拼历史。
    rewritten_q: str = Field(
        default="",
        description=(
            "结合对话历史改写后的自包含问题（润色后问题）：如果当前问题依赖历史才能理解"
            "（含代词、省略、追问如「详细一点」「那个呢」「继续」），输出改写后的完整问题；"
            "如果问题本身已经完整独立，原样返回用户问题。"
        ),
    )
