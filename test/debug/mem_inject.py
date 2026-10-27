# 在线触发真实压缩+时间回查（省 token 版）：灌 55 轮假历史（不走 LLM）→ 真发 2 轮
# 第56轮触发 summarize 真实压缩入库；第57轮 chat 回查"邮箱+什么时候说的"
# 用法：先起服务（8123）+ Docker Redis，再从项目根跑；输出同时落盘 test/output/mem_inject_result.txt（防终端通道断）
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx

from app.ai.graph.build import build_graph
from app.ai.mem import history as mem_history

BASE = "http://127.0.0.1:8123"
THREAD = "mem_live_t3"
os.makedirs("test/output", exist_ok=True)
OUT = open("test/output/mem_inject_result.txt", "w", encoding="utf-8")


def log(*a):
    print(*a, flush=True)
    print(*a, file=OUT, flush=True)


async def inject():
    graph = await build_graph()
    tid = f"u2018000101:{THREAD}"
    cfg = {"configurable": {"thread_id": tid}}
    hist = [(f"帮我查一下A酒店的基本信息发给王总", "好的，这是A酒店的信息邮件草稿（后取消）") for _ in range(55)]
    hist[12] = ("我的备用邮箱是 spare_test_2026@163.com，记住了", "好的，已记住您的备用邮箱 spare_test_2026@163.com")
    await graph.aupdate_state(cfg, {"history": hist})
    st = await graph.ainvoke({"question": "ping"}, cfg)   # 触发 summarize 条件边评估
    log(f"灌入完成：55 轮（第13轮埋邮箱），summary_upto={st.get('summary_upto', 0)}")


def ask(client, token, q):
    with client.stream("POST", f"{BASE}/chat", json={"question": q, "thread_id": THREAD},
                       headers={"Authorization": f"Bearer {token}"}, timeout=180) as r:
        frames = []
        for line in r.iter_lines():
            if line.startswith("data:"):
                try:
                    frames.append(json.loads(line[5:].strip()))
                except Exception:
                    pass
    if any(f.get("type") == "interrupt" for f in frames):
        with client.stream("POST", f"{BASE}/chat/resume",
                           json={"thread_id": THREAD, "confirm": False},
                           headers={"Authorization": f"Bearer {token}"}, timeout=60) as r2:
            for _ in r2.iter_lines():
                pass
        return "interrupt→cancelled"
    done = [f for f in frames if f.get("done")]
    return (done[-1].get("content") or "") if done else f"无done帧({len(frames)}帧)"


async def main():
    await inject()
    with httpx.Client() as client:
        r = client.post(f"{BASE}/auth/login", json={"employee_id": 2018000101, "password": "123456"})
        r.raise_for_status()
        token = r.json()["token"]
        log("登录 OK")
        log(f"[56] 你好 → {ask(client, token, '你好')}")
        log(f"[57] 回查 → {ask(client, token, '我之前跟你说过我的备用邮箱，是什么？我大概什么时候跟你说的？')}")
    OUT.close()


if __name__ == "__main__":
    asyncio.run(main())
