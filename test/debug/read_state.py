"""直读 checkpoint 验证压缩结果：mem_live_t3 的 state（摘要/facts/末两轮答复）+ mem_43 文本时间戳
（改记忆链路后的在线验证工具：SSE 答复落盘不可靠时，直接读 state 是最硬的证据）"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import redis

from app.ai.graph.build import build_graph
from app.ai.rag.builder import REDIS_HOST, REDIS_PORT

TID = "u2018000101:mem_live_t3"


async def main():
    g = await build_graph()
    st = await g.aget_state({"configurable": {"thread_id": TID}})
    v = st.values
    hist = v.get("history", [])
    print(f"== state == history={len(hist)} 轮 | summary_upto={v.get('summary_upto')} | history_deleted={v.get('history_deleted')}")
    print(f"== 摘要 ==\n{v.get('compressed_summary')}")
    print(f"== facts ==\n{json.dumps(v.get('memory_facts'), ensure_ascii=False)}")
    for q, a, ts in hist[-2:]:
        print(f"== {ts} ==\nQ: {q}\nA: {a}\n")

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=False)
    ks = list(r.scan_iter("mem_43:*"))
    print(f"== mem_43 == {len(ks)} docs")
    if ks:
        for f in r.hkeys(ks[0]):
            raw = r.hget(ks[0], f)
            try:
                print(f"{f.decode()}: {raw.decode('utf-8')[:300]}")
            except UnicodeDecodeError:
                print(f"{f.decode()}: <二进制 {len(raw)}B（向量）>")


asyncio.run(main())
