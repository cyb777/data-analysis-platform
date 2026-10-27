"""冒烟测试：图表智能体 · LangGraph 全链路（不启服务、不打 SSE，模拟 SSE 抓 chart_json）

用法：python test/test_chart.py
耗时：~3 分钟（4 个图表类问题，不启服务、不打 SSE，离线全链路）

注意：Checkpointer 是 AsyncRedisSaver，只能在事件循环内配合 graph.astream 使用
（同步 graph.stream 会因事件循环关闭报错），故本脚本整体 async。
"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from app.ai.graph.build import build_graph

logger.remove()
logger.add(sys.stdout, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

# 4 个图表类问题（与前端 4 个出图类推荐问题一致）
CHART_QUESTIONS = [
    "按渠道统计预订量，画个柱状图",
    "各渠道房费收入占比饼图",
    "最近 6 个月 RevPAR 趋势折线图",
    "按城市看入住率排名",
]

async def main():
    graph = await build_graph()
    thread_id = "smoke-chart-hotel-20261001"
    cfg = {"configurable": {"thread_id": thread_id}}

    results = []
    for i, q in enumerate(CHART_QUESTIONS, 1):
        logger.info("=" * 60)
        logger.info("Q{}/{}：{}", i, len(CHART_QUESTIONS), q)
        logger.info("=" * 60)

        state_in = {
            "question": q,
            "history": [],
            # route 权限门：chart 要经理级（level>=3），匿名（缺省=0）会被拦直连 END
            "user_level": 4,
        }

        try:
            final_state = None
            async for event in graph.astream(state_in, cfg, stream_mode="values"):
                final_state = event

            chart_json = (final_state or {}).get("chart_json") or {}
            answer = (final_state or {}).get("answer", "")
            route = (final_state or {}).get("route", "")

            has_chart = bool(chart_json)
            has_fallback = bool(chart_json.get("fallback_reason"))
            chart_type = chart_json.get("chart_type", "?")
            n_x = len(chart_json.get("x_axis", []))
            n_s = len(chart_json.get("series", []))

            status = "OK" if has_chart and not has_fallback else (
                "FALLBACK" if has_chart else "MISS"
            )

            logger.info("route          = {}", route)
            logger.info("chart_json keys= {}", list(chart_json.keys()))
            logger.info("chart_type     = {}", chart_type)
            logger.info("x_axis len     = {}", n_x)
            logger.info("series len     = {}", n_s)
            logger.info("fallback_reason= {}", chart_json.get("fallback_reason", "（无）"))
            logger.info("status         = {}", status)
            logger.info("answer head    = {}", answer[:60].replace("\n", " "))

            results.append({
                "q": q, "status": status, "chart_type": chart_type,
                "n_x": n_x, "n_s": n_s, "has_fallback": has_fallback,
            })
        except Exception as e:
            logger.exception("Q{} 异常：{}", i, e)
            results.append({"q": q, "status": "ERROR", "err": str(e)})

    # ====== 汇总 ======
    print("\n" + "=" * 60)
    print("汇总 · 真出图率（OK=无 fallback，图表真出）")
    print("=" * 60)
    ok = sum(1 for r in results if r.get("status") == "OK")
    fallback = sum(1 for r in results if r.get("status") == "FALLBACK")
    miss = sum(1 for r in results if r.get("status") == "MISS")
    err = sum(1 for r in results if r.get("status") == "ERROR")
    print(f"真出图 OK   = {ok}/{len(results)} = {ok*100//len(results)}%")
    print(f"走兜底      = {fallback}/{len(results)} = {fallback*100//len(results)}%")
    print(f"无图表      = {miss}/{len(results)}")
    print(f"异常        = {err}/{len(results)}")
    for i, r in enumerate(results, 1):
        print(f"  Q{i} {r.get('status'):8s}  {r.get('chart_type','?'):6s}  x={r.get('n_x','?')} s={r.get('n_s','?')}  fb={r.get('has_fallback',False)}  -- {r.get('q')[:30]}")


if __name__ == "__main__":
    asyncio.run(main())
