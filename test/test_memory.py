"""功能测试：三层记忆（mem/ 包）/ 压缩节奏 / 块提交原子性 / 冷层回查（离线，mock LLM 与向量库）

覆盖：
  1. should_compress 双参数节奏（未压尾部=history[upto:]：54 不压 / 55 压 / 混着已入库轮次时按 upto 折算）
  2. format_history / build_history_text
  3. merge_facts 同 key 覆盖
  4. 拼历史与冷层回查互不耦合：node_history_text 只拼热层+温层（不碰向量库）；recall_text 独立成段（query 优先 rewritten_q；upto=0/无 thread/无命中返回空段）
  5. 块提交成功（未超上限）：摘要追加、upto 推进、embed_turns 收到正确轮次、不截断（延迟截断）
  6. embedding 失败原子性：摘要/事实/upto/history 全不变 + 退避被置（mock redis）
  7. 幂等：同 (thread, 轮次) 重复 embed_turns，keys 完全一致且覆盖不翻倍
  8. thread_id_of 取值健壮性：config=None / 缺键 / 畸形 config / 空串都返回空（recall 与 summarize 共用一处口径）
  9. 语义回查：mock mem_recall 命中；内部异常被吞返回 ""（降级信号）
 10. 无 thread_id 路径：只摘要+事实+推进 upto，不调 embed_turns、不哨兵截断（单测不破）
 11. 无 thread 二次压缩：upto 折算切块不重压旧块；未压不足一块直接放行
 12. append_history 哨兵：int keep 才截断；用户输入 "__truncate__" 不误伤
 13. 延迟截断：len(history) > HISTORY_HARD_LIMIT(100) 才哨兵删最老一块；截断后双坐标（summary_upto 全局轮次 / 列表下标 = upto - history_deleted）不错位

运行：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_memory.py
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


# ====== 测试替身 ======

class FakeVectorStore:
    """记忆库替身：按 key 存 text（模拟确定性 key 覆盖语义），记录每次 add_texts"""
    def __init__(self):
        self.docs = {}          # key -> text
        self.add_calls = []     # 每次调用的 keys 列表

    def add_texts(self, texts, metadatas=None, keys=None):
        self.add_calls.append(list(keys))
        for k, t in zip(keys, texts):
            self.docs[k] = t    # 同 key 覆盖（与真实 Redis hash 一致）


def _fake_compress(chunk, start_turn):
    """compress_chunk 替身：不调 LLM，返回固定摘要+一条事实"""
    return f"■ 第{start_turn}-{start_turn + len(chunk) - 1}轮：测试摘要", [
        {"key": "口径", "content": "最近30天"}
    ]


def test_compress_rhythm():
    print("\n----- 1. should_compress 双参数节奏（未压尾部=history[upto:]） -----")
    from app.ai.mem.compress import should_compress, CHUNK_SIZE, KEEP_RECENT, HISTORY_HARD_LIMIT
    check("CHUNK_SIZE=50", CHUNK_SIZE == 50)
    check("KEEP_RECENT=5", KEEP_RECENT == 5)
    check("HISTORY_HARD_LIMIT=100", HISTORY_HARD_LIMIT == 100)
    check("空 history 不压缩", should_compress([]) is False)
    check("54 轮不压缩", should_compress([("q", "a")] * 54) is False)
    check("55 轮触发压缩", should_compress([("q", "a")] * 55) is True)
    check("104 轮大尾部必压", should_compress([("q", "a")] * 104) is True)
    # 延迟截断后 history 混着已入库轮次：未压尾部按 upto 折算
    check("105 轮 upto=50（尾部55）触发", should_compress([("q", "a")] * 105, 50) is True)
    check("104 轮 upto=50（尾部54）不压", should_compress([("q", "a")] * 104, 50) is False)
    check("155 轮 upto=100（尾部55）触发", should_compress([("q", "a")] * 155, 100) is True)
    # 截断后坐标：全量 = deleted + len(history)（physical 55 条但已聊 105 轮，尾部=5 不压）
    check("截断后 deleted 折算（尾部5）不压", should_compress([("q", "a")] * 55, 100, 50) is False)
    check("截断后 deleted 折算（尾部55）触发", should_compress([("q", "a")] * 105, 100, 50) is True)


def test_format_history():
    print("\n----- 2. format_history / build_history_text -----")
    from app.ai.mem.recall import format_history, build_history_text

    check("空 history=（暂无）", format_history([]) == "（暂无）")
    h3 = [("8月入住率", "75.2%", "10-24 15:20"), ("那 ADR 呢", "328元", "10-24 15:21")]
    fh3 = format_history(h3)
    check("三元组带时间戳",
          "【10-24 15:20】用户：8月入住率" in fh3 and "助手：328元" in fh3, fh3[:60])

    bt = build_history_text(h3, summary="早期摘要X")
    check("build_history_text 含摘要+时间戳+现在锚点",
          "早期摘要X" in bt and "【10-24 15:20】用户：8月入住率" in bt and "（现在：" in bt, bt[-70:])


def test_merge_facts():
    print("\n----- 3. merge_facts 同 key 覆盖 -----")
    from app.ai.mem.compress import merge_facts
    old = [{"key": "邮箱", "content": "a@x.com"}]
    new = [{"key": "邮箱", "content": "b@x.com"},
           {"key": "身份", "content": "老板"}]
    merged = merge_facts(old, new)
    keys = {f["key"]: f["content"] for f in merged}
    check("同 key 邮箱被新值覆盖", keys.get("邮箱") == "b@x.com", str(keys))
    check("新 key 身份被加入", keys.get("身份") == "老板")


def test_compress_structured():
    print("\n----- 3b. 压缩结构化输出（with_structured_output + key 归一 + 容错） -----")
    from app.ai.mem.compress import compress_chunk
    from app.ai.schemas.llm_compress_schema import CompressResult, CompressFact

    class _FakeStructured:
        def __init__(self, result): self._r = result
        def invoke(self, _msgs): return self._r

    class _FakeModel:
        def __init__(self, result): self._r = result
        def with_structured_output(self, _schema): return _FakeStructured(self._r)

    # 正常：摘要原样 + key 乱填归"其他" + 空 content 跳过
    result = CompressResult(
        summary="■ 第1-3轮：\n【结论】8月入住率75.2%、环比+3pt\n【待办】用户要对比 7 月数据",
        facts=[CompressFact(key="邮箱", content="a@x.com"),
               CompressFact(key="乱填", content="x"),
               CompressFact(key="口径", content="  ")],
    )
    summary, facts = compress_chunk(
        _FakeModel(result),
        [("q1", "a1", "10-24 09:10"), ("q2", "a2", "10-24 09:12"), ("q3", "a3", "10-25 14:30")], 1,
    )
    check("结构化摘要原样保留", "【结论】8月入住率75.2%" in summary and "【待办】" in summary, summary[:40])
    check("facts key 归一 + 空内容跳过",
          len(facts) == 2 and facts[0] == {"key": "邮箱", "content": "a@x.com"}
          and facts[1]["key"] == "其他", str(facts))

    # 缺摘要 → 失败信号（调用方置退避）
    empty = CompressResult(summary="  ", facts=[])
    check("缺摘要返回失败信号", compress_chunk(_FakeModel(empty), [("q", "a", "10-25 14:30")], 1) == ("", []))

    # invoke 抛异常 → 失败信号
    class _BoomModel:
        def with_structured_output(self, _s):
            raise ConnectionError("llm down")
    check("异常返回失败信号", compress_chunk(_BoomModel(), [("q", "a", "10-25 14:30")], 1) == ("", []))


def test_recall_unconditional():
    print("\n----- 4. 拼历史（node_history_text）与冷层回查（recall_text）互不耦合 -----")
    from app.ai.mem import recall as rc

    captured = {}

    def spy_recall(q, tid, top_k=2):
        captured.update(q=q, tid=tid, k=top_k)
        return "第3轮 用户：备用邮箱\n第3轮 助手：spare@x.com"

    cfg = {"configurable": {"thread_id": "u1:t"}}
    # 延迟截断语义：history 混着已入库轮次，热层=history[upto:]。51 轮（50 已入库+1 未压）
    base = {"history": [(f"问题{i}", f"回答{i}", "10-25 10:00") for i in range(1, 52)], "summary_upto": 50,
            "compressed_summary": "旧摘要", "memory_facts": [], "question": "8月房费营收"}

    # ① 拼历史不碰冷层：node_history_text 只拼热层+温层，完全不会调用 mem_recall
    captured.clear()
    with patch.object(rc.mem_history, "mem_recall", spy_recall):
        hist = rc.node_history_text(base)
    check("node_history_text 不碰向量库", captured == {})
    check("node_history_text 含热层+温层", "旧摘要" in hist and "【最近对话】" in hist
          and "用户：问题51" in hist)
    check("node_history_text 无【原文回查】段", "【原文回查】" not in hist)

    # ② 回查独立成段：recall_text 自己返回【原文回查】段（chat 拿到后自行拼接）
    with patch.object(rc.mem_history, "mem_recall", spy_recall):
        seg = rc.recall_text(base, cfg)
    check("recall_text 命中返回回查段", seg.startswith("【原文回查】") and "spare@x.com" in seg, seg[:30])
    check("recall_text 传对 thread_id/query",
          captured.get("tid") == "u1:t" and captured.get("q") == "8月房费营收", str(captured))
    check("两段拼接即 prompt 最终历史", "【原文回查】" in hist + "\n\n" + seg)

    # ③ query 优先用 rewritten_q（自包含），无则回退原始 question
    captured.clear()
    with patch.object(rc.mem_history, "mem_recall", spy_recall):
        rc.recall_text({**base, "question": "详细一点", "rewritten_q": "把各酒店入住率对比展开分析"}, cfg)
    check("query 优先 rewritten_q", captured.get("q") == "把各酒店入住率对比展开分析", str(captured))
    captured.clear()
    with patch.object(rc.mem_history, "mem_recall", spy_recall):
        rc.recall_text(base, cfg)   # 无 rewritten_q → 回退 question
    check("无 rewritten_q 回退 question", captured.get("q") == "8月房费营收", str(captured))

    # ④ upto=0（冷层还没建）/ 无 thread（向量库按线程隔离）：返回空段且不查
    captured.clear()
    check("upto=0 返回空段", rc.recall_text({**base, "summary_upto": 0, "compressed_summary": ""}, cfg) == "")
    check("无 config 返回空段", rc.recall_text(base, None) == "")
    check("两边界都没调 mem_recall", captured == {})

    # ⑤ mem_recall 无命中：返回空段（不注入空标题）
    with patch.object(rc.mem_history, "mem_recall", lambda q, t, top_k=2: ""):
        check("无命中返回空段", rc.recall_text(base, cfg) == "")


def test_block_commit():
    print("\n----- 5. 块提交成功·未超上限（摘要+upto+入库轮次，不截断） -----")
    import app.ai.nodes.summarize as sm

    history = [(f"问题{i}", f"回答{i}") for i in range(1, 56)]   # 55 轮 → chunk 50
    state = {"question": "问题55", "history": history, "summary_upto": 0,
             "compressed_summary": "", "memory_facts": []}
    captured = {}

    def fake_embed(thread_id, turns, start_turn):
        captured.update(thread_id=thread_id, n=len(turns), start_turn=start_turn)
        return True

    with patch.object(sm, "compress_chunk", lambda model, chunk, st: _fake_compress(chunk, st)), \
         patch.object(sm.mem_history, "embed_turns", fake_embed):
        out = sm.summarize_node(state, {"configurable": {"thread_id": "u1:t"}})

    check("摘要已追加", "测试摘要" in out.get("compressed_summary", ""))
    check("upto 推进 50", out.get("summary_upto") == 50)
    check("55 轮未超上限不截断（延迟截断）", "history" not in out, str(out.get("history")))
    check("embed_turns 轮次正确",
          captured.get("thread_id") == "u1:t" and captured.get("n") == 50
          and captured.get("start_turn") == 1, str(captured))


def test_embed_fail_atomic():
    print("\n----- 6. embedding 失败原子性（state 全不变 + 进程内退避） -----")
    import app.ai.nodes.summarize as sm

    history = [(f"问题{i}", f"回答{i}") for i in range(1, 56)]
    state = {"question": "问题55", "history": history, "summary_upto": 0,
             "compressed_summary": "旧摘要", "memory_facts": [{"key": "口径", "content": "旧"}]}

    with patch.object(sm, "compress_chunk", lambda model, chunk, st: _fake_compress(chunk, st)), \
         patch.object(sm.mem_history, "embed_turns", lambda *a: False):
        out = sm.summarize_node(state, {"configurable": {"thread_id": "u1:t"}})

    check("失败返回空 dict（state 不写）", out == {}, str(out))
    check("进程内退避已置", sm._backoff_local.get("u1:t", 0) > 0)
    sm._backoff_local.pop("u1:t", None)   # 清理，避免影响后续用例

    # 退避期内第二轮直接跳过：不再每轮空烧一次压缩 LLM
    calls = {"n": 0}

    def counting_compress(model, chunk, st):
        calls["n"] += 1
        return _fake_compress(chunk, st)

    cfg = {"configurable": {"thread_id": "u2:dead"}}
    with patch.object(sm, "compress_chunk", counting_compress), \
         patch.object(sm.mem_history, "embed_turns", lambda *a: False):
        sm.summarize_node(state, cfg)     # 第一次：入库失败 → 置退避
        sm.summarize_node(state, cfg)     # 第二次：退避期内直接跳过
    check("第一轮入库失败置退避", calls["n"] == 1, str(calls))
    check("第二轮被进程内退避挡住（不再空烧压缩）", calls["n"] == 1, str(calls))
    sm._backoff_local.pop("u2:dead", None)


def test_embed_idempotent():
    print("\n----- 7. 幂等：同 (thread,轮次) 重复入库不翻倍 -----")
    from app.ai.mem import history as mh

    vs = FakeVectorStore()
    turns = [(f"问题{i}", f"回答{i}", f"10-25 10:0{i}") for i in range(1, 4)]
    with patch.object(mh, "_get_memory_store", lambda: vs):
        ok1 = mh.embed_turns("u1:t", turns, 1)
        ok2 = mh.embed_turns("u1:t", turns, 1)   # 重压同一块
    check("两次入库都成功", ok1 and ok2)
    check("keys 完全一致", vs.add_calls[0] == vs.add_calls[1])
    check("覆盖不翻倍（3 条）", len(vs.docs) == 3, str(len(vs.docs)))
    check("文本带时间戳", "【10-25 10:02】用户：问题2" in list(vs.docs.values())[1])
    # tag 哈希化：纯 [a-z0-9_]（无 :/@/. —— 查询侧裸拼字符串，标点会破坏 TAG 语法）
    from app.ai.mem.history import mem_tag
    tag = mem_tag("u3:foo@bar.com")
    check("tag 哈希化无特殊字符",
          tag.startswith("mem_") and all(c.isalnum() for c in tag[4:]), tag)
    check("tag 不含冒号（避免裸拼进 TAG 查询语法）", ":" not in tag, tag)


def test_recall_boundary():
    print("\n----- 8. thread_id_of 取值健壮性（config 缺失/畸形） -----")
    from app.ai.mem import history as mh

    check("config=None → 空", mh.thread_id_of(None) == "")
    check("config 无 configurable 键 → 空", mh.thread_id_of({}) == "")
    check("configurable 无 thread_id → 空", mh.thread_id_of({"configurable": {}}) == "")
    check("正常取值", mh.thread_id_of({"configurable": {"thread_id": "u1:t"}}) == "u1:t")
    check("畸形 config（非 dict）→ 空", mh.thread_id_of("bad") == "")
    check("thread_id 为空串 → 空", mh.thread_id_of({"configurable": {"thread_id": ""}}) == "")


def test_semantic_recall():
    print("\n----- 9. 语义回查（命中 / 异常被吞返回空） -----")
    from app.ai.mem import recall as rc
    from app.ai.mem import history as mh

    obj = type("D", (), {"page_content": "第3轮 用户：我的备用邮箱是啥\n第3轮 助手：备用邮箱是 spare@x.com"})()
    state = {"question": "我之前留的邮箱", "history": [("问题51", "回答51")], "summary_upto": 50,
             "compressed_summary": "旧摘要", "memory_facts": []}

    with patch.object(rc.mem_history, "mem_recall", lambda q, t, top_k=2: "第3轮 用户：我的备用邮箱是啥\n第3轮 助手：备用邮箱是 spare@x.com"):
        txt = rc.recall_text(state, {"configurable": {"thread_id": "u1:t"}})
        check("语义命中进【原文回查】段", "【原文回查】" in txt and "spare@x.com" in txt)

    # 真实 mem_recall：store 抛异常时被吞返回 ""（降级信号）
    with patch.object(mh, "_get_memory_store", lambda: (_ for _ in ()).throw(ConnectionError("redis down"))):
        check("mem_recall 异常被吞返回空", mh.mem_recall("任何问题", "u1:t") == "")

    # rerank 返回 None → 退回向量顺序截断（不因精排挂掉丢回查）
    class _VS:
        def similarity_search_with_score(self, q, k=None, filter=None):
            return [(obj, 0.5)]

    with patch.object(mh, "_get_memory_store", lambda: _VS()), \
         patch.object(mh.retriever, "rerank", lambda q, docs, k: None):
        check("rerank 挂退回向量截断", "spare@x.com" in mh.mem_recall("邮箱", "u1:t"))


def test_no_thread_path():
    print("\n----- 10. 无 thread_id：只摘要+事实+推进，不截断不入库 -----")
    import app.ai.nodes.summarize as sm

    history = [(f"问题{i}", f"回答{i}") for i in range(1, 56)]
    state = {"question": "问题55", "history": history, "summary_upto": 0,
             "compressed_summary": "", "memory_facts": []}
    called = {"embed": False}

    def spy_embed(*a):
        called["embed"] = True
        return True

    with patch.object(sm, "compress_chunk", lambda model, chunk, st: _fake_compress(chunk, st)), \
         patch.object(sm.mem_history, "embed_turns", spy_embed):
        out = sm.summarize_node(state)   # 无 config（单测直连路径）

    check("摘要已追加", "测试摘要" in out.get("compressed_summary", ""))
    check("upto 推进 50", out.get("summary_upto") == 50)
    check("无 thread 不调 embed_turns", called["embed"] is False)
    check("无 thread 不截断（不写 history）", "history" not in out)


def test_no_thread_second_compress():
    print("\n----- 11. 无 thread 二次压缩：upto 折算切块 / 不足一块放行 -----")
    import app.ai.nodes.summarize as sm

    history = [(f"问题{i}", f"回答{i}") for i in range(1, 106)]  # 全量 105 轮（不截断）
    captured = {}

    def spy_compress(model, chunk, st):
        captured.update(n=len(chunk), start_turn=st, first=chunk[0] if chunk else None)
        return _fake_compress(chunk, st)

    # 守卫：upto=50、未压仅 1 轮（56 轮全量）→ 不足一块直接放行，不调 compress_chunk
    state_small = {"question": "q", "history": history[:56], "summary_upto": 50,
                   "compressed_summary": "旧摘要", "memory_facts": []}
    with patch.object(sm, "compress_chunk", spy_compress):
        out_small = sm.summarize_node(state_small)
    check("不足一块直接放行（返回 {}）", out_small == {}, str(out_small))
    check("守卫生效未调 compress_chunk", captured == {})

    # 二次压缩：upto=50、全量 105 轮 → 只切第 51~100 轮，不重压旧块
    state = {"question": "问题105", "history": history, "summary_upto": 50,
             "compressed_summary": "旧摘要", "memory_facts": []}
    with patch.object(sm, "compress_chunk", spy_compress):
        out = sm.summarize_node(state)

    check("二次压缩只切新块 50 轮", captured.get("n") == 50, str(captured))
    check("二次压缩 start_turn=51", captured.get("start_turn") == 51)
    check("二次压缩块首=问题51（不重压旧块）",
          captured.get("first") == ("问题51", "回答51"), str(captured.get("first")))
    check("upto 推进到 100", out.get("summary_upto") == 100)
    check("无 thread 不截断（不写 history）", "history" not in out)


def test_lazy_truncate():
    print("\n----- 13. 延迟截断：超上限删最老一块 + 截断后双坐标不错位 -----")
    import app.ai.nodes.summarize as sm
    from app.ai.mem.compress import should_compress
    from app.ai.mem.recall import node_history_text

    # ====== A. 截断已生效后的下一轮（P0 回归）：physical 55 条 = 全局 51~105 轮，
    #          upto=100、deleted=50 → 下标 100-50=50 切中第 101 轮，判断/热层都不能空 ======
    post = {"history": [(f"问题{i}", f"回答{i}", "10-25 10:00") for i in range(51, 106)],
            "summary_upto": 100, "history_deleted": 50,
            "compressed_summary": "旧摘要", "memory_facts": [], "question": "q"}
    check("截断后 should_compress 尾部=5 不压",
          should_compress(post["history"], 100, 50) is False)
    hot = node_history_text(post)
    check("截断后热层非空且尾部完整",
          "用户：问题101" in hot and "用户：问题105" in hot, hot[-40:])

    # ====== B. 首次截断（deleted=0）：105 轮 upto=50 → 再压一块后 len>100 → 删最老 50 ======
    state = {"question": "问题105", "summary_upto": 50, "history_deleted": 0,
             "history": [(f"问题{i}", f"回答{i}") for i in range(1, 106)],
             "compressed_summary": "旧摘要", "memory_facts": []}
    captured = {}

    def spy_compress(model, chunk, st):
        captured.update(n=len(chunk), start_turn=st, first=chunk[0] if chunk else None)
        return _fake_compress(chunk, st)

    with patch.object(sm, "compress_chunk", spy_compress), \
         patch.object(sm.mem_history, "embed_turns", lambda *a: True):
        out = sm.summarize_node(state, {"configurable": {"thread_id": "u1:t"}})

    check("首截切块 51~100（下标=upto-deleted）",
          captured.get("n") == 50 and captured.get("start_turn") == 51
          and captured.get("first") == ("问题51", "回答51"), str(captured))
    check("upto 推进到 100", out.get("summary_upto") == 100)
    check("首截哨兵 keep=55（删最老 50）", out.get("history") == [("__truncate__", 55)],
          str(out.get("history")))
    check("history_deleted 累加到 50", out.get("history_deleted") == 50)

    # ====== C. 截断后再压缩（稳态）：physical 105 条 = 全局 51~155 轮，
    #          upto=100、deleted=50 → 切块全局 101~150，删后 keep=55、deleted=100 ======
    state2 = {"question": "问题155", "summary_upto": 100, "history_deleted": 50,
              "history": [(f"问题{i}", f"回答{i}") for i in range(51, 156)],
              "compressed_summary": "旧摘要", "memory_facts": []}
    with patch.object(sm, "compress_chunk", spy_compress), \
         patch.object(sm.mem_history, "embed_turns", lambda *a: True):
        out2 = sm.summarize_node(state2, {"configurable": {"thread_id": "u1:t"}})
    check("截断后切块=全局 101~150 轮",
          captured.get("n") == 50 and captured.get("start_turn") == 101
          and captured.get("first") == ("问题101", "回答101"), str(captured))
    check("截断后 upto 推进到 150", out2.get("summary_upto") == 150)
    check("稳态截断 keep=55（未压尾部55）", out2.get("history") == [("__truncate__", 55)],
          str(out2.get("history")))
    check("history_deleted 累加到 100", out2.get("history_deleted") == 100)


def test_sentinel_guard():
    print("\n----- 12. append_history 哨兵守卫 -----")
    from app.ai.graph.state import append_history

    existing = [("q1", "a1"), ("q2", "a2"), ("q3", "a3")]
    out = append_history(existing, [("__truncate__", 2)])
    check("哨兵截断保留最近2轮", out == [("q2", "a2"), ("q3", "a3")], str(out))

    # 用户真输入 "__truncate__"：二元组第二项是 str，不得触发截断
    out2 = append_history(existing, [("__truncate__", "这是用户的正常问题")])
    check("用户输入 __truncate__ 不误伤", len(out2) == 4 and out2[-1][1] == "这是用户的正常问题")

    out3 = append_history(existing, [("__truncate__", 0)])
    check("keep=0 清空", out3 == [])

    out4 = append_history([], [("问题", "回答")])
    check("追加顺手打时间戳（二元组→三元组）", len(out4[0]) == 3 and len(out4[0][2]) == 16, str(out4))


def main():
    test_compress_rhythm()
    test_format_history()
    test_merge_facts()
    test_compress_structured()
    test_recall_unconditional()
    test_block_commit()
    test_embed_fail_atomic()
    test_embed_idempotent()
    test_recall_boundary()
    test_semantic_recall()
    test_no_thread_path()
    test_no_thread_second_compress()
    test_sentinel_guard()
    test_lazy_truncate()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
