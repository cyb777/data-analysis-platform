"""端到端测试：覆盖前端 11 个推荐问题（酒店版，解析 data: JSON.type 字段）

2026-09-10：从 tests/ 移到 test/（原来两个目录只差一个 s，容易看错；测试脚本统一放 test/）。
2026-10-01：全量酒店化——问题对齐 index.html 推荐语，compare 帧改判 chart，
           收件人按分公司老板/店长/前厅经理岗位。
2026-10-24：权限门收紧——db/chart/system 均要经理级（level>=3），先登录老板账号拿 JWT
           再跑演示路径；另加匿名对照组验证登录制 401 直拒。
输出文件也跟着改成相对本脚本目录，不再硬编码绝对路径。
"""
import os
import requests
import json
import time
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def test_question(idx, q, expected, token=None, timeout=300):
    print(f"\n--- [{idx}] 预期: {expected} ---")
    print(f"    问: {q[:50]}...")
    url = "http://127.0.0.1:8000/chat"
    headers = {"Authorization": "Bearer " + token} if token else {}
    # 线程名带时间戳：checkpointer 是 Redis 持久化，硬编码线程名会撞历史遗留的 HITL 断点
    try:
        r = requests.post(url,
                          json={"question": q, "thread_id": f"test_e2e_hotel_{idx}_{int(time.time())}"},
                          headers=headers, timeout=timeout, stream=True)
        if r.status_code != 200:
            print(f"    [FAIL] HTTP {r.status_code}")
            return None
        # SSE 帧只有 data 行（无 event 行），从 data JSON.type 取
        type_counts = {}
        all_frames = []
        chart_info = None
        system_info = None
        confirm_info = None
        text_chunks = []
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data:
                continue
            try:
                obj = json.loads(data)
            except Exception:
                continue
            t = obj.get("type", "?")
            type_counts[t] = type_counts.get(t, 0) + 1
            all_frames.append(obj)
            content = obj.get("content", "")
            if t == "text":
                text_chunks.append(content)
            elif t == "chart" and chart_info is None:
                # chart content 可能是 dict 也可能是 str
                if isinstance(content, str):
                    try:
                        chart_info = json.loads(content)
                    except Exception:
                        chart_info = {"raw": content}
                else:
                    chart_info = content
            elif t == "system" and system_info is None:
                system_info = content if isinstance(content, dict) else {"raw": str(content)[:200]}
            elif t == "confirm" and confirm_info is None:
                confirm_info = content
            elif t == "clarify":
                pass
        print(f"    [OK] HTTP 200, types: {type_counts}")
        if text_chunks:
            full_text = "".join(text_chunks)
            print(f"    文字长度: {len(full_text)}, 摘要: {full_text[:120]}")
        if chart_info:
            ct = chart_info.get("chart_type", "?")
            xa = len(chart_info.get("x_axis", []))
            se = len(chart_info.get("series", []))
            title = chart_info.get("title", "")
            print(f"    [CHART] type={ct}, x_axis={xa}, series={se}, title={title}")
        if confirm_info:
            print(f"    [CONFIRM] keys: {list(confirm_info.keys()) if isinstance(confirm_info, dict) else '?'}")
        if system_info:
            print(f"    [SYSTEM] {str(system_info)[:200]}")
        if "clarify" in type_counts:
            print(f"    [WARN] clarify 反问 ({type_counts['clarify']})")
        return type_counts
    except Exception as e:
        print(f"    [FAIL] 异常: {type(e).__name__}: {e}")
        return None


def login_boss():
    """登录分公司老板账号拿 JWT。

    2026-10-24 起 db/chart/system 三分支权限门均要经理级（level>=3），
    登录制：匿名 /chat 直接 401——取数/出图/发邮件/闲聊全部必须带身份。
    密码默认初始密码 123456，可用环境变量 E2E_PASSWORD 覆盖。
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from app.ai.tool.mysql_tool import query_one
        row = query_one("SELECT employee_id FROM employee WHERE position='分公司老板'")
        if not row:
            print("  [FAIL] employee 表没有分公司老板")
            return None
        emp_id = row[0]
    except Exception as e:
        print(f"  [FAIL] 查库拿老板编号失败（MySQL 未启动？）: {e}")
        return None
    r = requests.post("http://127.0.0.1:8000/auth/login",
                      json={"employee_id": emp_id, "password": os.getenv("E2E_PASSWORD", "123456")},
                      timeout=10)
    if r.status_code != 200:
        print(f"  [FAIL] 登录失败 HTTP {r.status_code}: {r.text[:120]}")
        return None
    print(f"  [OK] 已登录分公司老板（employee_id={emp_id}，level=4）")
    return r.json()["token"]


def test_anonymous_gate(results):
    """登录制验证（不带 token）：/chat 直接 401，不进图（体验模式已删）"""
    print("\n===== 1.5 登录制验证（不带 token → 401）=====")
    for q in ("8月入住率 TOP5 的酒店是哪些", "发上周经营报告给分公司老板"):
        try:
            r = requests.post("http://127.0.0.1:8000/chat",
                              json={"question": q, "thread_id": f"test_e2e_anon_{int(time.time())}"},
                              timeout=10)
            ok = r.status_code == 401
            print(f"  [{'OK' if ok else 'FAIL'}] 匿名问「{q[:16]}…」→ HTTP {r.status_code}（预期 401）")
            results.append((f"匿名:{q[:20]}", "401 直拒", {"text": 1} if ok else {}))
        except Exception as e:
            print(f"  [FAIL] 异常: {e}")
            results.append((f"匿名:{q[:20]}", "401 直拒", None))
        time.sleep(1)


def main():
    print("===== 0. 服务存活检查 =====")
    try:
        r = requests.head("http://127.0.0.1:8000/openapi.json", timeout=5)
        print(f"  [OK] 服务在线（HTTP {r.status_code}）")
    except Exception as e:
        print(f"  [FAIL] 服务不可达: {e}")
        return

    print("\n===== 0.5 登录拿 JWT（权限门：db/chart/system 均要经理级）=====")
    token = login_boss()
    if not token:
        print("  [FAIL] 无法登录，演示路径（取数/出图/发邮件）全要经理级身份，终止")
        return

    # 问题直接对齐前端 11 个推荐问题（index.html），保证测的是真实演示路径。
    # compare 节点已删：环比/门店对比类问题现在由 chart 分支出图，不再有 compare 帧。
    questions = [
        ("8月入住率 TOP5 的酒店是哪些", "db 纯查询"),
        ("8月平均房价 ADR 是多少", "db 纯查询"),
        ("按渠道统计预订量，画个柱状图", "chart 柱状图"),
        ("各渠道房费收入占比饼图", "chart 饼图"),
        ("最近 6 个月 RevPAR 趋势折线图", "chart 折线图"),
        ("按城市看入住率排名", "chart 柱状图"),
        ("比较8月和7月的入住率和 RevPAR 差异", "chart 对比出图"),
        ("对比各酒店的 OCC 和 ADR", "chart 对比出图"),
        ("把上周的酒店经营报告汇总发邮件给分公司老板", "system 邮件(HITL)"),
        ("检查未闭环的投诉并通知店长", "system 邮件(HITL)"),
        ("把本周差评清单发给前厅经理", "system 邮件(HITL)"),
    ]

    print(f"\n===== 1. 开始测试 {len(questions)} 个问题（每题间等 3s 让 Uvicorn 回收连接）=====")
    results = []
    for i, (q, expected) in enumerate(questions, 1):
        ev = test_question(i, q, expected, token=token)
        results.append((q[:30], expected, ev))
        time.sleep(3)  # 单 worker Uvicorn 必加，避免连接堆积把服务搞挂

    # 匿名对照组：验证登录制 401 直拒（不带 token）
    test_anonymous_gate(results)

    print("\n===== 2. 测试汇总 =====")
    print(f"  共测试 {len(results)} 个问题")
    success = 0
    fail = 0
    for q, expected, ev in results:
        if ev is None:
            fail += 1
            print(f"  [FAIL] {q}... 预期 {expected}，结果：异常")
            continue
        if "system" in expected.lower():
            # HITL：先出 confirm 帧；草稿失败降级时会出 system 帧，也算流程走通
            ok = "confirm" in ev or "system" in ev
        elif "chart" in expected.lower():
            ok = "chart" in ev
        else:
            ok = "text" in ev
        mark = "[OK]" if ok else "[FAIL]"
        if ok:
            success += 1
        else:
            fail += 1
        print(f"  {mark} {q}... 预期 {expected}，收到 {list(ev.keys())}")
    print(f"\n  成功: {success}/{len(results)}, 失败: {fail}")


if __name__ == "__main__":
    # v1.3 阶段 4 修：PowerShell + stream=True 输出缓冲 → 写文件
    out_dir = os.path.join(os.path.dirname(__file__) or ".", "output")
    os.makedirs(out_dir, exist_ok=True)
    output_file = os.path.join(out_dir, "e2e_result.txt")
    import io
    buf = io.StringIO()
    # 重定向 stdout
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        main()
    finally:
        sys.stdout = old_stdout
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print(f"结果已写入 {output_file}")
