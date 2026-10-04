# data_calc 工具的入参 schema。
# 只留三个 calc_type：求和/平均/最值/计数/排序由 LLM 心算，不走工具。
from typing import Literal
from pydantic import BaseModel, Field


class DataCalcSchema(BaseModel):
    """data_calc_tool 的参数：计算类型 + 参与计算的数值列表"""
    calc_type: Literal[
        "growth_rate",           # 环比/同比增长率：(current-previous)/previous*100，values=[current, previous]
        "ratio",                 # 占比：part/total*100，values=[part, total]
        # CAGR 涉及开 n 次方，LLM 心算容易错，留给工具算
        "compound_growth_rate",  # 复合增长率 CAGR：(end/start)**(1/n)-1，values=[start, end, n_years]
    ] = Field(..., description="计算类型")
    values: list = Field(..., description="参与计算的数值列表（按 calc_type 的说明顺序传）")
