"""ECharts 图表结构（前端可直接渲染）。"""
from pydantic import BaseModel, Field


class ChartData(BaseModel):
    """图表 JSON：chart 节点查完库，把数据组织成这个结构"""
    title: str = Field(..., description="图表标题")
    chart_type: str = Field(..., description="图表类型：bar / line / pie 三选一")
    x_axis: list = Field(..., description="X 轴类别列表，如 ['手机', '电脑', '耳机']")
    series: list = Field(..., description="与 x_axis 一一对应的数值列表，如 [50000, 30000, 12000]")
