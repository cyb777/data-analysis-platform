"""图的状态（State）：图里流转的"数据包"模板。

节点收 state 读数据、return dict 写数据（键名需与 State 字段对应）。
Annotated[list, add] = Reducer 累加器：同名字段多次写入时累加不覆盖（历史越滚越长）。
"""
from typing import Annotated, TypedDict
from operator import add


class State(TypedDict):
    """问题进来，资料查出来，回答出来"""
    question: str                       # 用户问题（进来就有的）
    route: str                          # 走哪条路（route 节点写下的路由结论）
    context: str                        # 查到的资料（rag/db/chart 节点写入）
    chart_json: dict = {}               # chart 节点单独存图表 JSON，API 层直接推给前端渲染
    answer: str                         # 最终回答（llm_node 写入）
    history: Annotated[list, add]       # 对话历史"只累加不覆盖"
    error_count: int                    # 重试节点记录失败次数（观察用）
