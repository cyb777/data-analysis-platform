"""clarify 节点：意图无法判断时的诚实出口——宁可反问也不瞎答

与默认时间口径的分工：缺 WHERE 条件（时间）由 db/chart 的智能体按最近30天自查，不反问；缺 WHAT TO DO（意图/指代）只能问。
触发场景：新会话第一句就无意图（"帮我看看"）、或指代悬空（无历史的"那个怎么样"）——
有历史时 standalone 改写已还原指代，轮不到本节点；它守的是记忆不存在的那一刻。
"""
from loguru import logger


def clarify_node(state):
    """澄清节点：route 判不出意图时走这里，固定模板反问用户补充信息"""
    q = state["question"]
    # 反问句用固定模板（意图导向：给个"能问什么"的示例清单，不预设用户一定要查数）
    answer = "请问您想了解哪方面的酒店经营数据？比如：某家酒店的入住率（OCC）、平均房价（ADR）和 RevPAR 趋势、各渠道预订占比、餐饮营收或差评投诉情况～"
    logger.info("  → clarify 节点输出反问：{}", answer[:40])
    return {"answer": answer, "history": [(q, answer)]}
