"""route 节点：LLM 按【语义】判断走哪条路（条件边的"判官"）

branch / rewritten_q 同一次结构化调用产出；收件人提取归邮件侧（dispatcher），本节点不管。
无关键词纠偏/兜底层：LLM 异常按顶层默认值走 chat（无工具的安全分支），本节点不查库。
"""
from loguru import logger
from langchain_core.prompts import ChatPromptTemplate

from app.ai.schemas.llm_route_schema import Route
from app.ai.model.model import MyModel
from app.ai.mem.recall import node_history_text   # 三层记忆组装收敛到公共层

# 路由专用轻量模型（doubao-seed-2.0-lite，见 MyModel.get_route_model）
_llm = MyModel.get_route_model()


def route_node(state):
    """路由节点：LLM 按【语义】判断走哪条路（条件边的"判官"）"""
    q = state["question"]
    # 热层+温层：关键事实 + 块摘要 + 未压原文带轮次编号。不做冷层回查（只在 chat 做，
    # 路由不需要还会干扰判断）；prompt 里把"回溯早期对话"类问题派给 chat
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
        - clarify：需要反问澄清。两种情况：
          ① 问题模糊到连要查什么都判断不出、且历史里也推断不出（如"帮我看看""那个怎么样"）；
          ② 用户在【对上一轮回答表达不满/否定】（如"不对""不是这个""答非所问"），
             说明上一轮理解错了，要重新猜他想问什么。
          仅缺时间范围不要反问——db/chart 没看到时间会默认按最近30天查
        - chat：普通聊天、总结、追问，及其他不取数的问题。
          还承接【回溯早期对话】类问题——用户引用自己早前说过的细节（"我之前留的邮箱是啥"
          "上次说的那个口径是什么"），要求回顾之前聊过的内容（"前面我们聊到哪儿了"
          "刚才那个结论怎么来的"）。这类问题要翻早前对话的原文，只有 chat 能回查 → 一律派 chat

        问题里有代词指代前文的人或事（如"它""那家店""那个渠道"）时，结合对话历史判断。
        判断口诀：指代靠 rewritten_q 就能还原成自包含的取数问题 → 照常派 db/chart/system；
        问题不取数、只是要翻回早期对话的原文或说法 → 派 chat（回查能力只在 chat）。
        上一轮助手若是反问澄清（给了编号候选列表），用户回"1""2""选3"这类序号表示在挑选候选：
        branch 按对应候选问题的语义判断，rewritten_q 改写成该候选的完整问题。
        用户说"老板"时，收件人角色按"分公司老板"理解。
        对话历史：{history}（较早的对话已被压缩成摘要，细节原文只有 chat 能回查）
        用户问题：{question}

        branch 只输出 rag、db、chart、system、clarify、chat 中的一个词。
        同时输出 rewritten_q：把用户问题改写成【脱离历史也能看懂】的自包含问题。
        例如历史里刚分析了"各酒店入住率对比"，用户追问"详细一点"，
        应改写为"把各酒店入住率对比的数据展开详细分析"；问题本身完整时原样返回即可。"""
    )
    # 顶层默认值（LLM 失败兜底时直接用）
    branch = "chat"
    rewritten_q_value = q
    # 结构化输出：Route 用 Literal 枚举，API 层面强制多选一；branch / rewritten_q 同一次调用产出
    route_model = _llm.with_structured_output(Route)
    try:
        result = (prompt | route_model).invoke({"question": q, "history": history_text})
        branch = result.branch
        # 入口改写：模型没填或填了空白时退回原问题，下游永远有值可用
        rewritten_q_value = (result.rewritten_q or "").strip() or q
        if rewritten_q_value != q:
            logger.info(f"  → 入口改写：「{q[:20]}」→「{rewritten_q_value[:30]}」")
    except Exception as e:
        # 兜底 = 顶层默认值（chat + 原问题）：chat 无工具，异常时不取数不发信，降级方向安全
        logger.warning(f"  → 路由结构化输出异常：{e}，兜底走 chat")

    logger.info(f"  → 模型路由判断「{q[:20]}...」走：{branch} 分支")

    # 权限门（全项目唯一收口点）：读 state.user_level（JWT 带入，不查库）
    # ==========================================================================
    # 分级规则：db/chart/system 均要经理级（level>=3）——经营数据查询与系统邮箱发信都不对
    # 普通员工/匿名开放（匿名 user_level=0 天然被拦）。越权自写 answer 直连 END，不烧下游节点
    user_level = state.get("user_level") or 0
    answer = None
    if branch in ("db", "chart", "system") and user_level < 3:
        what = "数据查询" if branch in ("db", "chart") else "邮件发送"
        answer = (f"当前账号无{what}权限：仅经理及以上岗位可用。"
                  "业务知识学习（指标口径、运营方法）可以随时问我～")
        logger.info(f"  → route：{branch} 越权拦截（user_id={state.get('user_id') or 0}, level={user_level}）")
    if answer:
        return {
            "route": "end",
            "answer": answer,
            "history": [(q, answer)],
            "chart_json": None,
            "rewritten_q": rewritten_q_value,
            "system_result": {},
        }

    return {
        "route": branch,
        "chart_json": None,
        # 入口改写后的自包含问题，下游 db/chart/writer/chat 拿它代替原始 question
        "rewritten_q": rewritten_q_value,
        "system_result": {},
    }
