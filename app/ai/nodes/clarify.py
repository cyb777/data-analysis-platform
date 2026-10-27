"""clarify 节点：反问澄清器——猜不准就【给编号候选】让用户回序号挑，而不是瞎答

两类触发（都由 route 派进来）：
  1) 提问太模糊：新会话第一句就没意图（"帮我看看"）、或指代悬空（无历史的"那个怎么样"）；
  2) 用户对上一轮回答不满/否定（"不对""不是这个""答非所问"）——上一轮把意图理解错了，
     这里结合历史重新猜他想问什么。

产出：纯文本反问（反问句 + 编号候选列表），全部走 answer——候选就写在文本里，
用户回"1/2/3"即视为选择：route 入口改写结合历史把序号还原成完整问题，下游零感知
（不需要前端按钮、不需要额外 state 字段，候选随 answer 自然进历史供下轮溯源）。
与默认时间口径的分工不变：只缺时间范围不反问（db/chart 的智能体按最近30天自查）；
只有缺 WHAT TO DO（意图/指代）才问。
"""
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate

from app.ai.model.model import MyModel
from app.ai.schemas.llm_clarify_schema import ClarifyGuess
from app.ai.mem.recall import node_history_text   # 三层记忆组装收敛到公共层

# 复用路由轻量模型（doubao-seed-2.0-lite）：一次「猜意图 + 写几个候选问题」，
# 和入口改写（rewritten_q）是同类轻活，不用主模型。
_llm = MyModel.get_route_model()

_PROMPT = ChatPromptTemplate.from_template(
    """你是连锁酒店经营分析助手的「反问澄清器」。
用户的话太模糊、或者他在对上一轮回答表达不满/否定，你需要【猜】他到底想问什么，
然后给出一句反问 + 几个具体候选问题让他挑，避免答非所问。

猜测方向（结合对话历史推断：他是在换门店 / 换时间 / 换指标 / 要对比 / 要图表 / 要建议？）：
酒店常用口径——OCC 入住率、ADR 平均房价、RevPAR、间夜量、各渠道预订占比、
OTA/直连佣金、餐饮营收、取消与 NoShow、差评投诉闭环。

要求：
1. missing_tip：一句人话反问，直接对用户说（如"你是想看哪家店的哪项指标？"）。
2. options：2-4 个候选问题，必须具体、带指标/时间/门店口径，彼此方向不同；
   不要输出与上一轮已经答过的内容重复的问题。
3. 全部用中文。

对话历史：
{history}

用户本轮输入：{question}"""
)

# LLM 失败兜底：只回一句平实反问（不带候选——LLM 都猜不出意图时，甩三个通用候选反而误导），请求不炸
_FALLBACK_TIP = "抱歉，我好像理解偏了。请问您想了解哪方面的酒店经营数据？"


def _format_answer(tip: str, options: list[str]) -> str:
    """把反问句 + 编号候选拼成一段纯文本 answer（用户回序号即视为选择）；无候选时只有反问句"""
    lines = [tip]
    if options:
        lines += ["", "你可以回复序号选择："]
        lines += [f"{i}. {opt}" for i, opt in enumerate(options, 1)]
        lines.append("也可以直接补充你的问题～")
    return "\n".join(lines)


def clarify_node(state):
    """反问节点：猜用户意图 → 输出带编号候选的反问文本（用户回序号继续）"""
    q = state["question"]
    # 热层+温层：猜意图要靠上文（不满场景尤其如此）。
    # 不做冷层回查（只在 chat 做），猜意图靠摘要/事实/热层尾部足够
    history_text = node_history_text(state)

    tip, options = _FALLBACK_TIP, []
    try:
        result = (_PROMPT | _llm.with_structured_output(ClarifyGuess)).invoke(
            {"question": q, "history": history_text}
        )
        tip = (result.missing_tip or "").strip() or _FALLBACK_TIP
        options = [o.strip() for o in (result.options or []) if o and o.strip()][:4]
    except Exception as e:
        logger.warning(f"  → clarify 猜测失败：{e}，只回反问句（无候选）")

    answer = _format_answer(tip, options)
    logger.info("  → clarify 反问：{}（候选 {} 个）", tip[:30], len(options))
    # 完整反问（含编号候选）随 answer 进历史——下轮用户回"1"时，
    # route 入口改写靠历史里的候选列表把序号还原成完整问题。
    return {"answer": answer, "history": [(q, answer)]}
