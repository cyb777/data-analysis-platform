# 记忆组装与回查层（route / writer / chat / clarify 统一经 node_history_text 访问历史）
#
#   热层  history[summary_upto - history_deleted:]（未压尾部，长度 5↔54 周期波动，永无空窗），注入时带时间戳
#   温层  ① memory_facts：关键事实清单（同 key 覆盖）
#         ② compressed_summary：块摘要拼接（每 50 轮一块，压一次即封存，只追加）
#   冷层  mem_43 向量索引（mem/history.py）：语义回查 mem_recall——独立入口 recall_text，
#         **只有 chat 调**（它承接追问/指代/溯源类问题）；不做词面/轮次编号兜底
#
# 两个入口互不耦合：node_history_text 只拼热层+温层（各节点都调），
# recall_text 只管冷层回查（chat 专属）——要回查的节点自己调它再拼接。
#
# 压缩在 mem/compress.py，冷层库在 mem/history.py。
from datetime import datetime

from loguru import logger

from app.ai.mem import history as mem_history


# 底层格式化：history / facts（各组函数共用的纯文本转换）
# ====================================================================
def format_history(history: list) -> str:
    """history → 带时间戳的简洁文本（route/writer/chat/compress 共用）；空 → （暂无）。
    元素 = (q, a, ts) 三元组，ts 由 append_history 追加时打——模型看到的时间坐标。"""
    lines = [f"【{ts}】用户：{q}\n助手：{a}" for q, a, ts in history]
    return "\n".join(lines) if lines else "（暂无）"


def format_facts(facts: list) -> str:
    """memory_facts → 文本。每条结构 {"key","content"}；写入时已保证预设 key 唯一（同 key 覆盖即新的赢）。"""
    lines = ["（梗概与事实矛盾以事实为准）"]
    for f in facts:
        lines.append(f"- [{f['key']}] {f['content']}")
    return "\n".join(lines)


# 对外入口：拼历史（人人可调）/ 冷层回查（chat 专属）
# ===================================================
def build_history_text(
    history: list,
    summary: str = "",
    facts: list = None,
) -> str:
    """喂给业务 prompt 的历史文本（热层 + 温层 + 当前时间锚点）。

    无 summary（前 50 轮）：直接带时间戳的完整原文。
    有 summary：【关键事实】+【历史摘要】+【最近对话=热层原文，带时间戳】。
    （现在：YYYY-MM-dd HH:mm）锚点：带完整年份（库数据超前真实日期，模型要拿它对照"昨天下午/上周"）。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    recent = f"（现在：{now}）\n" + format_history(history)
    if not summary:
        return recent

    parts = []
    if facts:
        parts.append("【关键事实】\n" + format_facts(facts))
    parts.append("【历史摘要】\n" + summary)
    parts.append("【最近对话】\n" + recent)
    return "\n\n".join(parts)


def node_history_text(state) -> str:
    """节点侧一行入口：拼【关键事实】+【历史摘要】+【最近对话（带时间戳）】，
    不含冷层回查——回查只在 chat，它自己调 recall_text 再拼接。
    热层 = history[upto - deleted:]（upto 是全局轮次，列表下标要扣掉已哨兵删除的轮次）。
    """
    history = state.get("history", [])
    upto = state.get("summary_upto", 0)
    deleted = state.get("history_deleted", 0)
    return build_history_text(
        history[upto - deleted:],
        state.get("compressed_summary", ""),
        state.get("memory_facts") or None,
    )


def recall_text(state, config=None) -> str:
    """冷层语义回查段（只有 chat 调）：有冷层（summary_upto>0）且能定位线程才查一次；
    命中返回【原文回查】段，无冷层/无 thread/无命中返回 ""（空段不注入）。
    query 取入口改写后的自包含问题，无改写回退原始 question。
    """
    upto = state.get("summary_upto", 0)
    thread_id = mem_history.thread_id_of(config)
    query = (state.get("rewritten_q") or "").strip() or state.get("question", "")
    if not (upto > 0 and thread_id and query):
        return ""
    hits = mem_history.mem_recall(query, thread_id, top_k=2)
    if not hits:
        return ""
    return (
        "【原文回查】\n"
        "以下是历史对话中与当前问题语义最相关的原文片段"
        "（与当前问题无关时忽略即可；引用历史内容时以原文为准并指出来源时间）：\n"
        + hits
    )
