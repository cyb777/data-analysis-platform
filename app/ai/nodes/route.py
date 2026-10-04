"""route 节点：LLM 按【语义】判断走哪条路（条件边的"判官"）

内含意图判断辅助函数（_is_system_intent / _extract_recipient_role）——
只在本节点用，不外露，不抽到独立文件。
"""
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate

from app.ai.schemas.llm_route_schema import Route
from app.ai.model.model import MyModel
from app.ai.graph.context_compressor import node_history_text   # 三层记忆组装收敛到公共层

# 路由专用轻量模型（doubao-seed-2.0-lite，见 MyModel.get_route_model）
_llm = MyModel.get_route_model()

# ====== 路由兜底关键词（仅 LLM 报错/校验失败时启用，主逻辑是 LLM 语义判断）======
# 顺序敏感：先 system → 再 rag → 再 chart → 再 db（命中即返回）
_ROUTE_FALLBACK_CHART = ("画", "图", "图表", "可视化", "趋势", "占比", "比例", "分布", "柱状", "饼图", "折线", "OCC", "ADR", "RevPAR", "入住率", "均价", "top", "看板", "大屏", "仪表盘", "分布图", "雷达图")
_ROUTE_FALLBACK_DB = ("多少", "查询", "统计", "排名", "最高", "最低", "几个", "哪些", "查一下", "间夜", "房费", "营收", "成本", "消费", "赚", "亏", "取消", "NoShow", "投诉", "走势")
_ROUTE_FALLBACK_RAG = ("什么", "怎么", "为什么", "如何", "定义", "原理", "区别", "哪个是", "怎么算", "怎么用", "怎么做")

# system 意图前置拦截（优先级最高，先于 LLM 语义判断）
# 含义明确的短语：子串命中即强制派 system，不靠 LLM 自由发挥
_SYSTEM_TRIGGER_KEYWORDS = (
    "发送", "发给", "发邮件", "发一份", "发个", "帮我发", "请发", "再发",
    "邮件", "mail", "催办", "提醒", "告警",
    "发通知", "推送通知", "推送邮件", "推送消息",
)
# 单字动词子串太宽（"批发/研发/发货""通知到达率""推送转化率"会误伤），
# 只有同时带收件人角色时才算动作（如"发报告给分公司老板""通知区域经理"）
_SYSTEM_VERBS_REQUIRE_RECIPIENT = ("发", "通知", "推送")
# 六个酒店岗位（顺序敏感：长词在前，先匹配"分公司老板"再匹配"老板"）
_SYSTEM_RECIPIENT_ROLES = ("分公司老板", "区域经理", "店长", "前厅经理", "客房经理", "餐饮经理", "老板")
# 默认收件人角色
_DEFAULT_RECIPIENT_ROLE = "分公司老板"
_NEGATION_KEYWORDS = ("怎么", "为什么", "什么是", "哪种", "哪类", "原理", "区别", "哪些", "怎么算", "怎么用", "怎么做")


def _normalize_role(role: str) -> str:
    """角色归一化：用户口头说的"老板"统一成"分公司老板" """
    if role == "老板":
        return "分公司老板"
    return role


def _extract_recipient_role(q: str) -> str:
    """从问题里粗提收件人 role"""
    for role in _SYSTEM_RECIPIENT_ROLES:
        if role in q:
            return _normalize_role(role)
    return _DEFAULT_RECIPIENT_ROLE  # 兜底默认


def _is_system_intent(q: str) -> bool:
    """判断是否发邮件/通知/催办意图
    命中明确短语，或「单字动词 + 收件人角色」，且不是知识类查询 → True
    """
    # 否定语境豁免：用户问"邮件里写了什么" / "通知怎么发的" 这种知识类问题不走 system
    if any(k in q for k in _NEGATION_KEYWORDS):
        return False
    if any(k in q for k in _SYSTEM_TRIGGER_KEYWORDS):
        return True
    # 单字"发/通知/推送"必须同时出现收件人角色才算动作（避免批发/研发/转化率误判）
    has_verb = any(v in q for v in _SYSTEM_VERBS_REQUIRE_RECIPIENT)
    has_recipient = any(r in q for r in _SYSTEM_RECIPIENT_ROLES)
    return has_verb and has_recipient


def _fallback_route(q: str) -> str:
    """LLM 路由失败时，用关键词做最小化兜底（不是主逻辑，主逻辑是 LLM 语义判断）"""
    # 兜底也优先判 system
    if _is_system_intent(q):
        return "system"
    if any(k in q for k in _ROUTE_FALLBACK_RAG):
        return "rag"
    if any(k in q for k in _ROUTE_FALLBACK_CHART):
        return "chart"
    if any(k in q for k in _ROUTE_FALLBACK_DB):
        return "db"
    return "chat"


def route_node(state):
    """路由节点：LLM 按【语义】判断走哪条路（条件边的"判官"）"""
    q = state["question"]
    # 三层记忆统一组装：关键事实 + 块摘要 + 未压块原文（溯源问题自动回查冷层）
    history_text = node_history_text(state)

    prompt = ChatPromptTemplate.from_template(
        """你是连锁酒店管理助手的智能路由判断器，根据用户问题的【语义】从下面 6 个分支里选一个：

        - rag：问指标口径/定义/业务知识（如"OCC 入住率怎么定义""RevPAR 的口径""ADR 是什么"）
        - db：查具体数据、文字回答即可（如"本月入住率多少""间夜量多少""各渠道预订量排名"
          "有多少笔取消/NoShow""未闭环的投诉有几条"）
        - chart：画图/可视化/图表分析（如"画个入住率趋势柱状图""做个 RevPAR 趋势图"）。
          以下表述即使没明说"画图"也走 chart（图表比文字直观）：
          占比/比例/趋势/分布/均价/排行，以及"对比/相比/vs"类对比问题
          （如"对比各店 OCC""各渠道房费收入占比""ADR 走势"）
        - system：发邮件/通知/提醒/催办，要让调度器查数据→写正文→发出去
          （如"发上周经营报告给分公司老板""把本周差评清单发给店长""通知区域经理参会"）
        - clarify：【极少用】问题模糊到连要查什么都判断不出、且历史里也推断不出时才用
          （如"帮我看看""那个怎么样"）。仅缺时间范围不要反问——db/chart 没看到时间会默认按最近30天查
        - chat：普通聊天、总结及其他不取数的问题

        问题里有代词指代前文的人或事（如"它""那家店""那个渠道"）时，结合对话历史判断。
        用户说"老板"时，收件人角色按"分公司老板"理解。
        对话历史：{history}
        用户问题：{question}

        branch 只输出 rag、db、chart、system、clarify、chat 中的一个词。
        同时输出 rewritten_q：把用户问题改写成【脱离历史也能看懂】的自包含问题。
        例如历史里刚分析了"各酒店入住率对比"，用户追问"详细一点"，
        应改写为"把各酒店入住率对比的数据展开详细分析"；问题本身完整时原样返回即可。"""
    )
    # 顶层默认值（各分支可能不调 LLM，必须先初始化防止 NameError）
    branch = "chat"
    rewritten_q_value = q
    recipient_role = ""
    # system 意图关键词前置拦截（优先级最高，不依赖 LLM 自由发挥）
    if _is_system_intent(q):
        branch = "system"
        recipient_role = _extract_recipient_role(q)
        logger.info(f"  → 关键词命中 system 意图，强制派 system 分支，收件人 role={recipient_role}")
    else:
        # 结构化输出：Route 用 Literal 枚举，API 层面强制多选一
        route_model = _llm.with_structured_output(Route)
        try:
            result = (prompt | route_model).invoke({"question": q, "history": history_text})
            branch = result.branch
            # 入口改写：模型没填或填了空白时退回原问题，下游永远有值可用
            rewritten_q_value = (result.rewritten_q or "").strip() or q
            if rewritten_q_value != q:
                logger.info(f"  → 入口改写：「{q[:20]}」→「{rewritten_q_value[:30]}」")
        except Exception as e:
            logger.warning(f"  → 路由结构化输出校验失败：{e}，按问题特征兜底")
            branch = _fallback_route(q)
            rewritten_q_value = q   # 兜底路径不调 LLM，问题原样下发
        recipient_role = _extract_recipient_role(q) if branch == "system" else ""

    logger.info(f"  → 模型路由判断「{q[:20]}...」走：{branch} 分支")
    return {
        "route": branch,
        "chart_json": None,
        "need_clarify": (branch == "clarify"),
        # 入口改写后的自包含问题，下游 db/chart/writer/chat 拿它代替原始 question
        "rewritten_q": rewritten_q_value,
        "system_result": {"recipient_role": recipient_role} if branch == "system" else {},
    }
