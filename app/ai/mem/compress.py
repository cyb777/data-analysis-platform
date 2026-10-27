# 记忆压缩层：分块判断 + 块压缩 + 事实合并（summarize 节点专用）
# 组装与回查在 mem/recall.py，冷层向量库在 mem/history.py。
#
# 要点：
#   1. 压缩只压未压尾部 history[summary_upto - history_deleted:]（扣最近 5 轮），输入大小恒定
#   2. 压缩是优化：失败由 summarize 置退避，不抛异常、不阻塞主流程
#   3. 攒够一块（should_compress：未压尾部扣最近 5 轮 ≥ 50 轮）才压，build.py 条件边也用它
#   4. history 延迟截断：入库后原文攒到 HISTORY_HARD_LIMIT 才删最老一块，未压尾部按 upto 折算
#   5. 压缩输出走 with_structured_output（对齐 clarify/route，不手写文本标记解析）
from loguru import logger
from langchain_core.messages import HumanMessage

from app.ai.mem.recall import format_history
from app.ai.schemas.llm_compress_schema import CompressResult

# 分块参数（50 轮版节奏：history 攒到 55 轮时压块①1~50；之后块②51~100、块③101~150……）
# ===================================================================================
CHUNK_SIZE = 50          # 每块 50 轮
KEEP_RECENT = 5          # 切点保留最近 5 轮（语境还在变，不封存）
HISTORY_HARD_LIMIT = 100 # history 延迟截断上限：超过才删最老一块已入库轮次（备份窗口≈1 块）

# 事实 key 固定类别（prompt 也按此输出）；同 key 新条目覆盖旧条目
FACT_KEYS = ("邮箱", "身份", "口径", "指标", "收件人")


# 压缩判断（summarize 节点 + build.py START 条件边共用同一个函数）
# ================================================================
def should_compress(history: list, summary_upto: int = 0, history_deleted: int = 0) -> bool:
    """是否攒够一块：未压尾部扣最近 KEEP_RECENT 轮后 ≥ CHUNK_SIZE。
    全量轮数 = history_deleted + len(history)（延迟截断会删已入库轮次），
    未压尾部 = 全量 - summary_upto；build.py 条件边同用。
    节奏：未压尾部攒到 55 轮时成立（第 56 轮进来时触发），之后每 50 轮一块。
    """
    return history_deleted + len(history) - summary_upto - KEEP_RECENT >= CHUNK_SIZE


# 分块压缩 + 事实抽取：结构化输出、跨块合并
# ===========================================
def compress_chunk(model, chunk: list, start_turn: int):
    """压缩一个块（chunk = history 未压尾部除去最近5轮），结构化输出：块摘要 + 块内事实。

    返回 (chunk_summary, facts)；失败返回 ("", [])，由调用方置退避（summarize 下轮自然重试）。
    块摘要是固定三段格式（结论/硬数据/待办），宁多勿漏——非 chat 分支拿不到冷层原文，
    对早期对话的全部认知就是摘要+事实，硬数据段是跨轮数字连续性的兜底。
    facts: [{"key","content"}, ...]（本段内的原始条目，尚未跨块合并）
    """
    end_turn = start_turn + len(chunk) - 1
    chunk_text = format_history(chunk)
    span = f"{chunk[0][2]}~{chunk[-1][2]}"   # 每轮第三位是时间戳（append_history 追加时打）

    compress_prompt = f"""请把以下一段对话（第 {start_turn}~{end_turn} 轮）压缩成结构化结果。

summary 填块摘要，按下面三段固定格式。原则：宁多勿漏——具体数字、结论、约定一条都不许丢，
不确定归哪段的放进【硬数据】；不要写"这段对话讨论了…"这类过程描述。
■ {span}：
【结论】本段得出的结论/答案，逐条一行（含数字结论，如"8月入住率75.2%、环比+3pt"；≤6 条，没有写：无）
【硬数据】用户给出或查询得到的关键数字/时间/金额/比率/名单/阈值等，逐条一行（≤8 条，没有写：无）
【待办】没聊完的疑问、用户说"待会/下次"的事、需要跟进的事（≤3 条，没有写：无）

facts 填本段中用户给出的、后续作答必须记住的关键事实（每条 = 类别 + 内容；没有则给空表）：
- 类别只能取：{'/'.join(FACT_KEYS)}/其他
- 类别含义：邮箱=联系方式；身份=用户身份/角色；口径=统计口径/时间范围；指标=指标数值与目标；收件人=邮件/通知对象

对话原文：
{chunk_text}"""

    # 重试 3 次：lite 模型 timeout=25 对压缩重活偏紧，偶发超时/格式不稳重试即恢复；
    # 全部失败才返回 ("", []) 由调用方置退避（下轮自然重试）
    last_err = None
    for attempt in range(1, 4):
        try:
            result = model.with_structured_output(CompressResult).invoke(
                [HumanMessage(content=compress_prompt)]
            )
            summary = (result.summary or "").strip()
            if not summary:
                raise ValueError("压缩输出缺摘要")
            # 后处理：key 不在预设类别归"其他"（与 merge_facts 的追加语义对应）；空内容跳过
            facts = [
                {"key": f.key if f.key in FACT_KEYS else "其他", "content": f.content.strip()}
                for f in (result.facts or []) if f.content and f.content.strip()
            ]
            logger.info(f"对话块已压缩：第 {start_turn}-{end_turn} 轮（{len(chunk)} 轮），事实 {len(facts)} 条")
            return summary, facts
        except Exception as e:
            last_err = e
            logger.warning(f"  → 压缩第 {attempt}/3 次失败：{e}")
    logger.error(f"对话块压缩失败（不影响主流程）：{last_err}")
    return "", []


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
