# 三层记忆的组装与压缩层（route / writer / chat / summarize 统一经此文件访问历史）
#
#   热层  尚未压块的原文 history[summary_upto:]（长度 5↔54 周期波动，永无空窗）
#   温层  ① memory_facts：关键事实清单（同 key 覆盖、带来源轮次）
#         ② compressed_summary：块摘要拼接（每 50 轮一块，压一次即封存，只追加）
#   冷层  history 全部原文（永不截断），溯源类提问时 recall_history 临时捞回
#
# 要点：
#   ① 压缩只压新增块 history[summary_upto:-5]，旧块不再碰，输入大小恒定
#   ② 压缩是优化：失败由 summarize 置 Redis 退避，不抛异常、不阻塞主流程
#   ③ 攒够一块（should_compress：未压原文扣最近 5 轮 ≥ 50 轮）才压，build.py 条件边也用它
#
# 本文件函数按自顶向下排列：压缩判断 → M1/M2 压缩 → 对外组装入口 → M4 回查 → 底层格式化。
import re

import jieba
from loguru import logger
from langchain_core.messages import HumanMessage

# ============================================================
# 分块参数（50 轮版节奏：第55轮块①1~50 → 第105轮块②51~100 → 155……）
# ============================================================
CHUNK_SIZE = 50          # 每块 50 轮
KEEP_RECENT = 5          # 切点保留最近 5 轮（语境还在变，不封存）
MAX_HISTORY_SOFT_CAP = 500  # history 软上限：超过 summarize 打 warning（监控 checkpointer 涨）

# 事实 key 固定类别（prompt 也按此输出）；同 key 新条目覆盖旧条目
FACT_KEYS = ("邮箱", "身份", "口径", "指标", "收件人")


# ============================================================
# 压缩判断（summarize 节点 + build.py START 条件边共用同一个函数）
# ============================================================
def should_compress(history: list, summary_upto: int = 0) -> bool:
    """是否攒够一块：未压块原文扣除最近 KEEP_RECENT 轮后 ≥ CHUNK_SIZE。
    节奏：upto=0 时第55轮触发（块①1~50）；之后第105轮块②（51~100）、155……每块整齐 50 轮。
    upto=0 的首批闸门也由它表达（len(history)-5 ≥ 50 即 len ≥ 55），不再单设函数。
    """
    return len(history) - KEEP_RECENT - summary_upto >= CHUNK_SIZE


# ============================================================
# M1/M2 分块压缩 + 事实抽取：压缩 prompt、输出解析、跨块合并
# ============================================================
def compress_chunk(model, chunk: list, start_turn: int):
    """压缩一个块（chunk = history[summary_upto:-5]），双段输出：块摘要 + 块内事实。

    返回 (chunk_summary, facts)；失败返回 ("", [])，由调用方置退避。
    facts: [{"key","turn","content"}, ...]（本段内的原始条目，尚未跨块合并）
    """
    end_turn = start_turn + len(chunk) - 1
    chunk_text = _format_history_for_llm(chunk, start_turn)

    compress_prompt = f"""请处理以下一段对话（第 {start_turn}~{end_turn} 轮），严格输出两部分：

【摘要】
用 2~5 句话概括这段对话的经过，其中提到的时间/金额/数字等硬数据要保留。只输出一行：
■ 第{start_turn}-{end_turn}轮：<梗概>

【事实】
逐行列出本段中用户给出的、后续作答必须记住的关键事实，每行一条，格式严格为：
类别|第N轮|内容
- 类别只能取：{'/'.join(FACT_KEYS)}/其他
- 类别含义：邮箱=联系方式；身份=用户身份/角色；口径=统计口径/时间范围；指标=指标数值与目标；收件人=邮件/通知对象
- N 填该事实出现的全局轮次（{start_turn}~{end_turn}）
- 没有关键事实则在【事实】下一行写：无
- 除这两部分外不要输出任何字

对话原文：
{chunk_text}"""

    try:
        response = model.invoke([HumanMessage(content=compress_prompt)])
        text = response.content if isinstance(response.content, str) else str(response.content)
        summary, facts = _parse_compress_output(text.strip())
        if not summary:
            raise ValueError("压缩输出缺少摘要段")
        logger.info(f"对话块已压缩：第 {start_turn}-{end_turn} 轮（{len(chunk)} 轮），事实 {len(facts)} 条")
        return summary, facts
    except Exception as e:
        logger.error(f"对话块压缩失败（不影响主流程）：{e}")
        return "", []


def _parse_compress_output(text: str):
    """解析双段输出 → (summary, facts)。标记缺失时容错：整体当摘要、事实为空。"""
    # 按 【摘要】/【事实】 标记切分（标记允许同行或换行）
    m_sum = re.search(r"【摘要】\s*", text)
    m_fact = re.search(r"【事实】\s*", text)
    if not m_sum or not m_fact or m_sum.start() > m_fact.start():
        return text.strip(), []

    summary = text[m_sum.end():m_fact.start()].strip()
    fact_block = text[m_fact.end():].strip()

    facts = []
    for line in fact_block.splitlines():
        line = line.strip().lstrip("-*").strip()
        if not line or line == "无":
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        key, turn_s, content = parts[0].strip(), parts[1].strip(), parts[2].strip()
        turn_m = re.search(r"\d+", turn_s)
        if key not in FACT_KEYS:
            key = "其他"
        if not turn_m or not content:
            continue
        facts.append({"key": key, "turn": int(turn_m.group()), "content": content})
    return summary, facts


def merge_facts(old_facts: list, new_facts: list) -> list:
    """跨块事实合并：预设 key 同 key 新条目替换旧条目；key=其他 一律追加。
    替换即冲突消解——后压的块轮次更大，天然「以轮次大的为准」。
    """
    result = list(old_facts or [])
    for f in new_facts:
        if f["key"] == "其他":
            result.append(f)
            continue
        for i, existing in enumerate(result):
            if existing["key"] == f["key"]:
                result[i] = f
                break
        else:
            result.append(f)
    return result


# ============================================================
# 对外组装：三段式文本 + 节点侧统一入口（route / writer / chat 只调这两个）
# ============================================================
def build_history_text(
    history: list,
    summary: str = "",
    facts: list = None,
    summary_upto: int = 0,
    recall: str = "",
) -> str:
    """喂给业务 prompt 的历史文本（三段式 + 可选原文回查段）。

    无 summary（前 50 轮）：直接完整原文。
    有 summary：【关键事实】+【历史摘要】+【最近对话=history[summary_upto:] 未压块原文】。
    recall：M4 冷层命中的原文片段，有则追加第四段。
    """
    if not summary:
        return format_history(history)

    parts = []
    if facts:
        parts.append("【关键事实】\n" + format_facts(facts))
    parts.append("【历史摘要】\n" + summary)
    parts.append("【最近对话】\n" + format_history(history[summary_upto:]))
    if recall:
        parts.append("【原文回查】\n" + recall)
    return "\n\n".join(parts)


def node_history_text(state) -> str:
    """节点侧一行入口：route/writer/chat 都调它，自动按 state 组装三段并做冷层回查。"""
    history = state.get("history", [])
    upto = state.get("summary_upto", 0)
    recall = ""
    question = state.get("question", "")
    # 仅当冷层已存在（upto>0）且问题带溯源/指代表达时才回查
    if upto > 0 and need_recall(question):
        hits = recall_history(question, history[:upto], top_k=2)
        if hits:
            recall = (
                "以下是从早期对话中检索到的原文，回答溯源问题时以原文为准并指出来源轮次：\n"
                + hits
            )
    return build_history_text(
        history,
        state.get("compressed_summary", ""),
        state.get("memory_facts") or None,
        upto,
        recall,
    )


# ============================================================
# M4 冷层回查：溯源/指代表达识别 + 冷层原文检索
# ============================================================

# 溯源/指代表达
_RETRACE_PATTERNS = (
    "第几轮", "第几次", "我什么时候", "我之前", "我上次", "刚才", "前面说",
    "之前说", "上次说", "以前说", "哪次", "那句", "那个", "提到过",
)
_TURN_RE = re.compile(r"第\s*(\d+)\s*[轮次]")


def need_recall(question: str) -> bool:
    """问题是否带溯源/指代表达（含明确的「第N轮」）"""
    if _TURN_RE.search(question):
        return True
    return any(p in question for p in _RETRACE_PATTERNS)


def _q_tokens(text: str) -> set:
    """轻量中文/英文分词：长度>1 的词 + 数字/英文标识符整体保留"""
    return {w.strip() for w in jieba.cut(text) if len(w.strip()) > 1}


def recall_history(question: str, cold_history: list, top_k: int = 2) -> str:
    """在冷层原文中检索与问题相关的问答片段，带轮次编号返回；无命中返回 ""。

    两种命中：
    - 明确「第N轮」：直接取该轮原文；
    - 指代/溯源：分词命中打分取 top_k（用户问 + 助手答一起计分）。
    """
    m = _TURN_RE.search(question)
    if m:
        n = int(m.group(1))
        if 1 <= n <= len(cold_history):
            return _format_turns(cold_history[n - 1:n], n)
        return ""

    q_tokens = _q_tokens(question)
    if not q_tokens:
        return ""

    scored = []
    for i, item in enumerate(cold_history):
        if isinstance(item, (list, tuple)) and len(item) == 2:
            text = f"{item[0]} {item[1]}"
        else:
            text = str(item)
        score = len(q_tokens & _q_tokens(text))
        if score > 0:
            scored.append((score, i))
    if not scored:
        return ""

    scored.sort(key=lambda x: (-x[0], x[1]))
    picks = sorted(i for _, i in scored[:top_k])
    return _format_turns([cold_history[i] for i in picks], picks[0] + 1)


# ============================================================
# 底层格式化：history / facts / 带轮次原文（各组函数共用的纯文本转换）
# ============================================================
def format_history(history: list) -> str:
    """history → 给业务 prompt 看的简洁文本（无轮次编号，route / writer / chat 共用）"""
    if not history:
        return "（暂无）"
    lines = []
    for item in history:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            u, a = item
            lines.append(f"用户：{u}\n助手：{a}")
        else:
            lines.append(f"用户：{item}")
    return "\n".join(lines)


def format_facts(facts: list) -> str:
    """memory_facts → 文本。每条结构 {"key","turn","content"}；写入时已保证预设 key 唯一。"""
    lines = ["（梗概与事实矛盾以事实为准；事实间矛盾以轮次大的为准）"]
    for f in facts:
        lines.append(f"- [{f['key']}]（第{f['turn']}轮）{f['content']}")
    return "\n".join(lines)


def _format_turns(turns: list, start_turn: int) -> str:
    """把若干轮原文带轮次编号输出（回查段用，编号为全局轮次）"""
    lines = []
    for offset, item in enumerate(turns):
        n = start_turn + offset
        if isinstance(item, (list, tuple)) and len(item) == 2:
            lines.append(f"第{n}轮 用户：{item[0]}\n第{n}轮 助手：{item[1]}")
        else:
            lines.append(f"第{n}轮：{item}")
    return "\n".join(lines)


def _format_history_for_llm(history: list, start_turn: int = 1) -> str:
    """history → 带全局轮次编号的纯文本（喂压缩 prompt；start_turn 为本段第一轮的全局轮次）"""
    lines = []
    for i, item in enumerate(history):
        n = start_turn + i
        if isinstance(item, (list, tuple)) and len(item) == 2:
            u, a = item
            lines.append(f"第{n}轮 用户：{u}\n第{n}轮 助手：{a}")
        elif isinstance(item, str):
            lines.append(f"第{n}轮：{item}")
        else:
            lines.append(f"第{n}轮：{str(item)}")
    return "\n".join(lines)
