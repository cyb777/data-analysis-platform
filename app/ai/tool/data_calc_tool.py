# 数据计算工具层：只兜 LLM 容易算错的三类计算（增长率/占比/CAGR），
# 简单算术（求和/平均/最值/计数/排序）由 LLM 心算，不走工具。
from langchain.tools import tool
from loguru import logger
from app.ai.schemas.tool_calc_schema import DataCalcSchema


@tool("data_calc", args_schema=DataCalcSchema)
def data_calc_tool(calc_type: str, values: list) -> str:
    """
    精确数值计算工具（只处理容易算错的三类，简单算术请直接心算）。
      - growth_rate 增长率(%)：values=[当期值, 上期值]
      - ratio 占比(%)：values=[部分值, 总值]
      - compound_growth_rate 复合增长率 CAGR(%)：values=[起始值, 结束值, 年数]
    """
    try:
        nums = [float(v) for v in values]

        if calc_type == "growth_rate":
            current, previous = nums[0], nums[1]
            if previous == 0:
                return f"增长率：分母为0无法计算（当期={current}, 基期=0）"
            rate = (current - previous) / previous * 100
            return (
                f"环比/同比增长率计算：(当期{current} - 基期{previous}) / 基期{previous} × 100%\n"
                f"  = ({current - previous}) / {previous} × 100%\n"
                f"  = {round(rate, 2)}%"
            )

        if calc_type == "ratio":
            part, total = nums[0], nums[1]
            if total == 0:
                return f"占比：分母为0无法计算（部分={part}, 总值=0）"
            rate = part / total * 100
            return (
                f"占比计算：部分{part} / 总值{total} × 100%\n"
                f"  = {round(rate, 2)}%"
            )

        if calc_type == "compound_growth_rate":
            start, end, n = nums[0], nums[1], int(nums[2])
            if start == 0 or n <= 0:
                return f"CAGR：起始值为0或年数<=0无法计算（start={start}, end={end}, n={n}）"
            cagr = ((end / start) ** (1 / n) - 1) * 100
            return (
                f"复合增长率 CAGR 计算：(结束值{end}/起始值{start})^(1/{n}) - 1) × 100%\n"
                f"  = ({round(end/start, 4)}^(1/{n}) - 1) × 100%\n"
                f"  = {round(cagr, 2)}%"
            )

        return f"未知计算类型：{calc_type}"
    except Exception as e:
        logger.error("data_calc_tool 计算失败：{}", e)
        return f"计算失败：{e}"
