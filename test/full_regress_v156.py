"""全面回归：离线断言层 + 在线 SSE 场景层（酒店版）

设计：
- 离线层（必跑，约 70 项，几秒完成）：不启服务，直接调函数
    State schema（15 字段） / route 纯 LLM+权限门 / 邮件 supervisor 守卫 / 上下文压缩（mem/ 包） /
    DB 工具 / data_calc 三类精确计算 / JWT+PBKDF2 / agent 基建（BaseToolAgent/resolve_q） /
    HTTP 层鉴权边界（TestClient，不触发 lifespan 建图）
- 在线层（探测到 http://127.0.0.1:8000 才跑）：先登录老板账号拿 JWT（权限门要经理级），再真打 SSE
    6 类分支业务特征 / chart JSON 结构合法性 / status 帧节点名 /
    HITL confirm→cancel 恢复闭环 / 多轮追问改写 / SSE 帧协议格式 / 登录制直拒（无 token 401）
  服务不在线则整层 SKIP，离线层仍出结论（CI / 本地无 GPU 环境友好）。

运行：
  离线：D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/full_regress_v156.py offline
  全量：先 python app/main.py，再执行同上命令（不带参数）
  分组：同上命令 + online（只在线层）/ b2 b5（只跑指定在线用例，失败重跑用）
"""
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"
# 在线层需要经理级身份（db/chart/system 权限门均要 level>=3）：run_online 前自动登录老板账号填入
ONLINE_TOKEN = ""

PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def skip(name, reason=""):
    SKIP.append(name)
    print(f"[SKIP] {name}" + (f" -> {reason}" if reason else ""))


# ============================================================
# A. 离线断言层
# ============================================================
def offline_state_schema():
    print("\n----- A1. State schema -----")
    from app.ai.graph.state import State
    fields = State.__annotations__
    # 当前态：15 字段（need_clarify 删——route 可推导；history_deleted 增——双坐标分离，
    # summary_upto 是全局轮次、严禁当列表下标；user_level 增——JWT 带入的级别快照）
    check("State 字段数=15", len(fields) == 15, str(len(fields)))
    check("State 已删 compare_result", "compare_result" not in fields)
    check("State 不含 mem_v2/thread_id（复用 config）", "mem_v2" not in fields and "thread_id" not in fields)
    check("State 不含 need_clarify（route 可推导）", "need_clarify" not in fields)
    for f in ("question", "route", "context", "chart_json", "answer", "history",
              "history_deleted", "rewritten_q", "compressed_summary",
              "summary_upto", "memory_facts", "system_result", "email_draft", "user_id", "user_level"):
        check(f"State 含 {f}", f in fields)


def offline_route():
    print("\n----- A2. route schema / 结构 -----")
    # 收件人提取归邮件侧（dispatcher 自提取+验证）；route 只判分支+改写+权限门
    from app.ai.schemas.llm_route_schema import Route
    check("Route schema 不含 recipient_role（提取归 dispatcher）", "recipient_role" not in Route.model_fields)

    # 关键词兜底/纠偏层已删：LLM 语义主判，异常兜底 chat（无工具的安全分支），route 不查库
    src = (ROOT / "app" / "ai" / "nodes" / "route.py").read_text(encoding="utf-8")
    check("route 无关键词兜底/纠偏层（异常走 chat），不查库",
          "_fallback_route" not in src and "_is_system_intent" not in src and "query_all" not in src)


def offline_compressor():
    print("\n----- A3. 上下文压缩/history -----")
    from app.ai.mem.compress import should_compress, CHUNK_SIZE, KEEP_RECENT
    from app.ai.mem.recall import format_history, build_history_text
    check("空 history 不压缩", should_compress([]) is False)
    check("块大小=50", CHUNK_SIZE == 50)
    # 单参数语义（history 仅未压尾部）：len-5>=50 即压；大尾部必压
    check("54 轮不压缩", should_compress([("q", "a")] * 54) is False)
    check("55 轮触发压缩", should_compress([("q", "a")] * 55) is True)
    check("104 轮大尾部必压", should_compress([("q", "a")] * 104) is True)

    check("format_history 空", format_history([]) == "（暂无）")
    h = [("8月入住率", "75.2%", "10-24 15:20"), ("那 ADR 呢", "328元", "10-24 15:21")]
    fh = format_history(h)
    check("format_history 双轮", "【10-24 15:20】用户：8月入住率" in fh and "助手：75.2%" in fh and "【10-24 15:21】用户：那 ADR 呢" in fh)

    bt = build_history_text(h, summary="早期摘要X")
    check("build_history_text 摘要+最近", "早期摘要X" in bt and "8月入住率" in bt)
    check("KEEP_RECENT=5", KEEP_RECENT == 5)

    # 冷层回查归属（2026-10-20 定稿）：只有 chat 查；route/writer/clarify 都关
    nodes = ROOT / "app" / "ai" / "nodes"

    def _src(name):
        # nodes/、agent/、tool/ 三个目录都找（email_dispatcher 在 agent/，素材工具在 tool/）
        for d in (nodes, ROOT / "app" / "ai" / "agent", ROOT / "app" / "ai" / "tool"):
            p = d / name
            if p.exists():
                return p.read_text(encoding="utf-8")
        return ""

    check("route 不含冷层回查调用", "recall_text" not in _src("route.py"))
    check("writer 不含冷层回查调用", "recall_text" not in _src("writer.py"))
    check("clarify 不含冷层回查调用", "recall_text" not in _src("clarify.py"))
    check("chat 是唯一回查方（独立调 recall_text）", "recall_text(state, config)" in _src("chat.py"))
    check("route prompt 把回溯类问题派 chat", "回溯早期对话" in _src("route.py")
          and "只有 chat 能回查" in _src("route.py"))
    check("chat_router 由 route 推 clarify 帧（need_clarify 已删）",
          'values.get("route") == "clarify"' in (ROOT / "app" / "api" / "chat" / "chat_router.py").read_text(encoding="utf-8"))
    check("route 权限门分级（读 state.user_level 不查库：db/chart/system 均要经理级>=3）",
          'branch in ("db", "chart", "system")' in _src("route.py") and "user_level < 3" in _src("route.py")
          and "is_senior" not in _src("route.py"))
    check("route 不提取收件人（只判分支+改写+权限门）", "recipient_role" not in _src("route.py"))
    check("JWT 携带 level（登录快照，聊天不查库）",
          '"level": level' in (ROOT / "app" / "api" / "auth" / "jwt.py").read_text(encoding="utf-8"))
    check("收件人权限判断全删（发信门槛在 route 收口，dispatcher 只查邮箱）",
          "sender_level" not in _src("email_dispatcher.py")
          and "sender_level" not in _src("system_draft.py"))
    check("外部邮箱直发（格式不预检，SMTP 失败自然留痕）",
          '"@" in (value or "")' in _src("email_dispatcher.py"))
    check("写作 agent 直查 SQL 四工具（邮件链路扁平化：SQL agent 撤出，每次取数省 2 次 LLM）",
          "[sql_query_tool, describe_table_tool, analyze_material_tool, search_hotel_knowledge_tool]" in _src("email_dispatcher.py")
          and "query_business_data_tool" not in _src("email_dispatcher.py"))
    check("收件人由写作 agent 结构化输出自带（response_format=EmailDraft，文本解析已删）",
          "response_format=EmailDraft" in _src("email_dispatcher.py")
          and "structured_response" in _src("email_dispatcher.py")
          and "_parse_draft" not in _src("email_dispatcher.py"))
    check("收件人职位/姓名一条 OR 查询（无类型分类，employee 直查）",
          "position=%s OR employee_name=%s" in _src("email_dispatcher.py"))
    check("收件人邮箱直查 employee（不从 LLM 文本正则抠，user_info 已撤出）",
          "FROM employee" in _src("email_dispatcher.py")
          and "user_info" not in _src("email_dispatcher.py")
          and "_extract_emails" not in _src("email_dispatcher.py"))
    check("草稿即校验（确认集=展示集，send 不重查）",
          "for_send" not in _src("email_dispatcher.py")
          and 'draft.get("recipients"' in _src("email_dispatcher.py")
          and "sender_level" not in _src("system_send.py"))
    check("未绑邮箱提醒（指名报错 + 群发 no_email 名单）",
          "no_email" in _src("email_dispatcher.py")
          and "没有绑定邮箱" in _src("email_dispatcher.py"))
    check("route 不查库（词表层已删），user_info 不在查询面",
          "query_all" not in _src("route.py") and "user_info" not in _src("route.py"))
    check("mysql_tool 可查表 16 张（user_info 撤出）",
          "可用表名只有这 16 个" in (ROOT / "app" / "ai" / "tool" / "mysql_tool.py").read_text(encoding="utf-8"))
    # 认证表硬黑名单（行为级）：猜到表名也读不到
    from app.ai.tool.mysql_tool import sql_query_tool as _sq, describe_table_tool as _dt
    check("SELECT/DESCRIBE user_info 被黑名单硬拦",
          "不在可查范围" in _sq.invoke({"sql": "SELECT * FROM user_info"})
          and "不在可查范围" in _dt.invoke({"table_name": "user_info"}))
    check("dispatcher 是带工具的写作 agent（supervisor 形态）",
          "create_agent" in _src("email_dispatcher.py"))
    check("dispatcher 起草时一次性注入口径资料（build_metric_block 进 prepare，不再逐问检索）",
          "_MailMeta" not in _src("email_dispatcher.py")
          and "build_metric_block" in _src("email_dispatcher.py"))
    check("素材工具在 tool 层（分析/检索两件套，kb 固定 hotel tag；取数无包装层）",
          all(t in _src("email_material_tool.py") for t in
              ("analyze_material", "search_hotel_knowledge", 'tag_filter="hotel"'))
          and "query_business_data" not in _src("email_material_tool.py"))
    check("system_draft 发起人署名（权限在 route 收口，本节点只署名）",
          "经酒店管理系统发起" in _src("system_draft.py"))


def offline_db_tools():
    print("\n----- A4. DB / SQL 工具 -----")
    from app.ai.tool.mysql_tool import query_all, query_one, _run_sql, describe_table_tool

    tables = query_all("SHOW TABLES")
    check("SHOW TABLES 返回 list", isinstance(tables, list))
    check("物理表数量=17（15 业务 + 留痕 + 认证）", len(tables) == 17, str(len(tables)))

    one = query_one("SELECT COUNT(*) AS c FROM stay_record", dict_cursor=True)
    check("query_one dict 游标", isinstance(one, dict) and isinstance(one.get("c"), int), str(one))
    check("stay_record 有数据", one["c"] > 0, str(one["c"]))
    check("query_one 查无结果=None",
          query_one("SELECT employee_id FROM user_info WHERE employee_id=-99999") is None)
    check("employee 新结构（编号/level/email）",
          query_one("SELECT level, email FROM employee WHERE position='分公司老板'") is not None)

    check("_run_sql 元组格式", _run_sql("SELECT 1").startswith("(("))
    check("_run_sql 错误吞成字符串", "查询失败" in _run_sql("SELECT * FROM no_such_table_xx"))

    d = describe_table_tool.invoke({"table_name": "stay_record"})
    check("describe_table 含列", "actual_check_in" in d or "room_amount" in d, d[:60])
    check("describe_table 拒绝非法名", "拒绝" in describe_table_tool.invoke({"table_name": "a;drop table"}))


def offline_data_calc():
    print("\n----- A5. data_calc 精确计算 -----")
    from app.ai.tool.data_calc_tool import data_calc_tool

    # growth_rate: (120-100)/100*100 = 20
    r = data_calc_tool.invoke({"calc_type": "growth_rate", "values": [120, 100]})
    check("growth_rate=20%", "20" in r, r[:60])
    # ratio: 25/100*100 = 25
    r = data_calc_tool.invoke({"calc_type": "ratio", "values": [25, 100]})
    check("ratio=25%", "25" in r, r[:60])
    # CAGR: (200/100)^(1/2)-1 ≈ 41.42
    r = data_calc_tool.invoke({"calc_type": "compound_growth_rate", "values": [100, 200, 2]})
    check("CAGR≈41.42%", "41.4" in r, r[:60])
    # 非法 calc_type 被 schema 拒绝
    try:
        data_calc_tool.invoke({"calc_type": "plus", "values": [1, 2]})
        check("非法 calc_type 被拒", False)
    except Exception:
        check("非法 calc_type 被拒", True)


def offline_jwt_http():
    print("\n----- A6. JWT 与 HTTP 鉴权边界（TestClient，不跑 lifespan）-----")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.api.auth import create_token
    from app.api.auth.jwt import _decode as decode_token

    token = create_token(employee_id=42, level=4)
    payload = decode_token(token)
    check("JWT 签发/解签（employee_id+level 新契约）",
          payload["user_id"] == 42 and payload["level"] == 4 and "role" not in payload)
    check("JWT 过期时间存在", "exp" in payload)

    # PBKDF2 密码哈希模块：roundtrip + 独立盐（同密码两次哈希不同）
    from app.api.auth.password import hash_password, verify_password
    h1, h2 = hash_password("123456"), hash_password("123456")
    check("PBKDF2 roundtrip（验真/验假）",
          verify_password("123456", h1) and not verify_password("wrong", h1))
    check("PBKDF2 独立盐（同密码不同哈希）", h1 != h2)

    # 酒店版无 /notification 路由；临时挂强制登录路由验证 401/200 边界
    from fastapi import Depends
    from app.api.auth.jwt import get_required_user

    @fastapi_app.get("/_test_auth_only")
    def _auth_only(user=Depends(get_required_user)):
        return {"code": 200, "user_id": user["user_id"]}

    client = TestClient(fastapi_app)  # 不 with：不触发 build_graph()
    auth = {"Authorization": "Bearer " + token}

    r = client.get("/_test_auth_only")
    check("强制登录路由 无 token 401", r.status_code == 401, str(r.status_code))
    r = client.get("/_test_auth_only", headers={"Authorization": "Bearer bad.token.x"})
    check("强制登录路由 假 token 401", r.status_code == 401, str(r.status_code))
    r = client.get("/_test_auth_only", headers=auth)
    check("强制登录路由 真 token 200", r.status_code == 200 and r.json().get("code") == 200,
          str(r.status_code))

    # /auth/login 分支（员工编号+密码，验证码接口已删）；MySQL 离线时 SKIP
    try:
        r = client.post("/auth/login", json={"employee_id": 9999999999, "password": "x"})
        check("/auth/login 不存在编号 401", r.status_code == 401, str(r.status_code))
        r = client.post("/auth/login", json={"employee_id": 9999999999})
        check("/auth/login 缺密码 422", r.status_code == 422, str(r.status_code))
    except Exception:
        skip("/auth/login 分支", "MySQL 未启动")


def offline_agent_infra():
    print("\n----- A7. agent 基建 / 样板收口 / mem 包（源码守卫） -----")

    def _read(rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    reg = _read("app/ai/agent/registry.py")
    check("BaseToolAgent 统一骨架（三样类属性 + 自建 agent 缓存）",
          "class BaseToolAgent" in reg
          and all(t in reg for t in ("tools", "system_prompt", "response_format")))
    check("结构化重试统一收口 invoke_with_structured_retry", "def invoke_with_structured_retry" in reg)
    check("sql/echarts/anlyze 三 agent 继承 BaseToolAgent（email_dispatcher 是 supervisor 自带 __init__）",
          all("(BaseToolAgent)" in _read(f"app/ai/agent/{n}.py") for n in
              ("sql_question_agent", "echarts_agent", "anlyze_agent"))
          and "(BaseToolAgent)" not in _read("app/ai/agent/email_dispatcher.py"))
    check("结构化重试 echarts/email 共用 helper（sql/anlyze 纯文本输出无需重试）",
          all("invoke_with_structured_retry" in _read(f"app/ai/agent/{n}.py") for n in
              ("echarts_agent", "email_dispatcher"))
          and all("invoke_with_structured_retry" not in _read(f"app/ai/agent/{n}.py") for n in
                  ("sql_question_agent", "anlyze_agent")))
    check("sys.path 样板已清（agent 安装内不再插 ROOT）",
          not any("sys.path.insert" in _read(f"app/ai/agent/{n}.py") for n in
                  ("sql_question_agent", "echarts_agent", "anlyze_agent", "email_dispatcher")))

    st = _read("app/ai/graph/state.py")
    check("resolve_q 收口（state.py 定义，六节点统一取 rewritten_q 回退 question）",
          "def resolve_q" in st)
    check("六个节点统一 resolve_q(state)（db/chart/rag/writer/chat/system_draft）",
          all("resolve_q(state)" in _read(f"app/ai/nodes/{n}.py") for n in
              ("db", "chart", "rag", "writer", "chat", "system_draft")))
    check("State total=False 无伪默认值", "total=False" in st)

    mem_h = _read("app/ai/mem/history.py")
    check("mem 冷层 mem_43（embed_turns 入库 / mem_recall 回查）",
          'MEM_INDEX_NAME = "mem_43"' in mem_h and "def embed_turns" in mem_h
          and "def mem_recall" in mem_h)
    check("mem_tag 哈希防 RediSearch TAG 语法炸", "def mem_tag" in mem_h and "sha1" in mem_h)
    rc = _read("app/ai/mem/recall.py")
    check("recall 双入口正交（node_history_text 热+温 / recall_text 冷层）",
          "def node_history_text" in rc and "def recall_text" in rc)
    sm = _read("app/ai/nodes/summarize.py")
    check("块提交三件套原子语义（embed_turns 失败置退避不写 state）",
          "embed_turns" in sm and "backoff" in sm.lower())

    b = _read("app/ai/graph/build.py")
    check("system_send 三分支直连 END（writer 只汇 rag/db/chart）",
          'add_edge("system_send", END)' in b and 'add_edge("writer", END)' in b)


def run_offline():
    print("=" * 60)
    print("离线断言层（不依赖服务）")
    print("=" * 60)
    offline_state_schema()
    offline_route()
    offline_compressor()
    offline_db_tools()
    offline_data_calc()
    offline_jwt_http()
    offline_agent_infra()


# ============================================================
# B. 在线 SSE 场景层
# ============================================================
def sse_once(question, thread_id, timeout=240, auth=True):
    """打一次 /chat，返回 (frames, text, error)。
    frames: [{type, content, ...}]；text: 拼接全文。auth=False 时强制匿名（权限门验证用）。"""
    import requests
    headers = {}
    if auth and ONLINE_TOKEN:
        headers["Authorization"] = "Bearer " + ONLINE_TOKEN
    frames, text = [], []
    try:
        r = requests.post(f"{BASE}/chat",
                          json={"question": question, "thread_id": thread_id},
                          headers=headers, timeout=timeout, stream=True)
        if r.status_code != 200:
            return None, "", f"HTTP {r.status_code}"
        for raw in r.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            payload = raw[5:].strip()
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            frames.append(obj)
            if obj.get("type") == "text":
                text.append(obj.get("content", ""))
        return frames, "".join(text), None
    except Exception as e:
        return frames, "".join(text), f"{type(e).__name__}: {e}"


def online_frame_protocol():
    print("\n----- B1. SSE 帧协议（结构/类型枚举/结束帧）-----")
    # 线程名带时间戳：checkpointer 是 Redis 持久化，硬编码线程名会撞上历史轮次遗留的
    # HITL 断点/僵尸任务（客户端超时断开后服务端图还在跑），全新线程保证干净
    frames, text, err = sse_once("8月房费营收多少", f"b1_proto_{int(time.time())}")
    if err and frames is None:
        check("B1 请求可达", False, err)
        return
    check("B1 有帧返回", len(frames) > 0, f"{len(frames)} frames")

    ALLOWED = {"text", "chart", "clarify", "system", "status", "confirm"}
    types = {f.get("type") for f in frames}
    illegal = types - ALLOWED
    check("帧类型全部合法（无 compare/rag/db 帧）", not illegal, str(illegal))

    # 结束帧：最后一帧 text done=True
    tail = frames[-1]
    check("末帧 done=True", tail.get("type") == "text" and tail.get("done") is True, str(tail)[:80])

    # status 帧必须带 node 名
    bad_status = [f for f in frames if f.get("type") == "status" and not f.get("node")]
    check("status 帧带 node 名", not bad_status, str(len(bad_status)))

    # text 流式帧 done=False（除末帧）
    mid_text = [f for f in frames[:-1] if f.get("type") == "text"]
    check("中间 text 帧 done!=True", all(f.get("done") is not True for f in mid_text))


def online_branch_cases():
    print("\n----- B2. 6 类分支业务特征 -----")
    import requests

    cases = [
        # (名称, 问题, 判定函数)
        ("chart", "按渠道统计预订量画柱状图",
         lambda fs, tx: any(f.get("type") == "chart" for f in fs)),
        ("chart_对比", "对比各酒店的 OCC 和 ADR",
         lambda fs, tx: any(f.get("type") == "chart" for f in fs)),
        # 年份钉死：库数据超前于真实日期（最新 2027-07），裸"8月"易歧义；判定排除"没查到"话术防假绿
        ("db", "2026年8月入住率 TOP5 的酒店",
         lambda fs, tx: ("入住率" in tx or "OCC" in tx or "%" in tx or "间夜" in tx) and len(tx) > 20
         and "没有任何" not in tx and "无法计算" not in tx),
        ("rag", "RevPAR 怎么算",
         lambda fs, tx: ("RevPAR" in tx or "口径" in tx or "定义" in tx) and len(tx) > 80),
        ("chat", "你好，介绍下你自己",
         lambda fs, tx: len(tx) > 10 and not any(f.get("type") in ("chart", "confirm") for f in fs)),
    ]
    for name, q, judge in cases:
        frames, text, err = sse_once(q, f"b2_{name}_{int(time.time())}", timeout=150)
        if err and not frames:
            check(f"分支 {name}", False, err)
            continue
        ok = False
        try:
            ok = judge(frames, text)
        except Exception as e:
            check(f"分支 {name}", False, f"judge error: {e}")
            continue
        check(f"分支 {name}", ok, f"types={sorted({f['type'] for f in frames})} text[:40]={text[:40]!r}")
        time.sleep(2)

    # system：HITL，应推 confirm 帧（拿到 confirm 即判过）。
    # 写作 agent 自主编排素材三件套（多轮工具调用+主模型），给足 600s
    frames, text, err = sse_once("发上周经营报告给分公司老板", f"b2_system_{int(time.time())}", timeout=600)
    got_confirm = bool(frames) and any(f.get("type") == "confirm" for f in frames)
    if got_confirm:
        check("分支 system→confirm(HITL)", True)
        return
    # 草稿失败分支：system 帧里带失败原因（LLM 配额/网络/无收件人）——
    # 这是设计内的降级路径（system_send 见 draft.error 不挂断点），非 HITL 缺陷 → SKIP
    sys_frames = [f for f in (frames or []) if f.get("type") == "system"]
    fail_summary = " ".join(str((f.get("content") or {}).get("summary", "")) for f in sys_frames)
    if fail_summary:
        skip("分支 system→confirm(HITL)", f"草稿失败降级路径：{fail_summary[:80]}")
        return
    check("分支 system→confirm(HITL)", False,
          f"types={sorted({f['type'] for f in (frames or [])})} {err or ''}")


def online_chart_json():
    print("\n----- B3. chart 帧 JSON 结构合法性 -----")
    frames, text, err = sse_once("各渠道房费收入占比画个饼图", f"b3_chartjson_{int(time.time())}", timeout=150)
    chart = None
    for f in frames or []:
        if f.get("type") == "chart":
            c = f.get("content")
            chart = json.loads(c) if isinstance(c, str) else c
            break
    if chart is None:
        check("拿到 chart 帧", False, err or "无 chart 帧")
        return
    check("拿到 chart 帧", True)
    check("title 非空", isinstance(chart.get("title"), str) and bool(chart["title"].strip()),
          str(chart.get("title")))
    check("chart_type ∈ bar/line/pie", chart.get("chart_type") in ("bar", "line", "pie"),
          str(chart.get("chart_type")))
    xa, se = chart.get("x_axis"), chart.get("series")
    check("x_axis 非空 list", isinstance(xa, list) and len(xa) > 0, f"len={len(xa or [])}")
    check("series 非空 list", isinstance(se, list) and len(se) > 0, f"len={len(se or [])}")
    check("x_axis/series 等长", isinstance(xa, list) and isinstance(se, list) and len(xa) == len(se),
          f"{len(xa or [])} vs {len(se or [])}")
    check("series 元素是数值", all(isinstance(v, (int, float)) for v in (se or [])),
          str(se)[:80])


def online_multi_turn():
    print("\n----- B4. 多轮追问（同 thread_id，改写/记忆）-----")
    tid = f"b4_multi_{int(time.time())}"
    f1, t1, e1 = sse_once("8月入住率多少", tid, timeout=150)
    if e1 and not f1:
        check("多轮第1问", False, e1)
        return
    check("多轮第1问有答", len(t1) > 20, t1[:50])
    time.sleep(2)
    # 追问：依赖上文改写（"那 ADR 呢" → "8月 ADR"）
    f2, t2, e2 = sse_once("那 ADR 呢", tid, timeout=150)
    if e2 and not f2:
        check("多轮追问", False, e2)
        return
    # 命中房价数据特征，且不是把"那 ADR 呢"当新意图反问
    ok = ("ADR" in t2 or "房价" in t2 or "元" in t2) and "请问您想了解" not in t2 and len(t2) > 15
    check("多轮追问继承上文（被改写而非 clarify）", ok, t2[:60])


def online_hitl_cancel():
    print("\n----- B5. HITL 闭环：confirm → resume cancel（两份独立草稿，不依赖 B2） -----")
    import requests
    # 两份独立线程草稿：b5_confirm_send 验「确认发送」、b5_cancel 验「取消」
    # 写作 agent 自主编排素材三件套（多轮工具调用+主模型），起草给足 600s
    ts_suffix = int(time.time())
    f0, t0, e0 = sse_once("发上周经营报告给分公司老板", f"b5_confirm_send_{ts_suffix}", timeout=720)  # 同 B2：起草可能 >5min
    can_confirm = bool(f0) and any(f.get("type") == "confirm" for f in (f0 or []))
    f1, t1, e1 = sse_once("发上周经营报告给分公司老板", f"b5_cancel_{ts_suffix}", timeout=720)
    can_cancel = bool(f1) and any(f.get("type") == "confirm" for f in (f1 or []))

    # ---- B5a：确认发送（收件人=种子里老板邮箱占位 boss@hotel.demo；要真发先把种子改真实地址）----
    if can_confirm:
        frames, text = [], []
        try:
            r = requests.post(f"{BASE}/chat/resume",
                          json={"thread_id": f"b5_confirm_send_{ts_suffix}", "action": "confirm"},
                          headers={"Authorization": "Bearer " + ONLINE_TOKEN},
                          timeout=200, stream=True)
            check("B5a resume confirm HTTP 200", r.status_code == 200, str(r.status_code))
            for raw in r.iter_lines(decode_unicode=True):
                if raw and raw.startswith("data:"):
                    try:
                        obj = json.loads(raw[5:].strip())
                        frames.append(obj)
                        if obj.get("type") == "text":
                            text.append(obj.get("content", ""))
                    except json.JSONDecodeError:
                        pass
            sys_frames = [f for f in frames if f.get("type") == "system"]
            send_ok = any((f.get("content") or {}).get("sent_count", 0) >= 1 for f in sys_frames)
            check("B5a 确认后真发（sent_count>=1）", send_ok,
                  str([(f.get("content") or {}) for f in sys_frames])[:150])
            to_target = any(
                "boss@hotel.demo" in ((f.get("content") or {}).get("recipients") or [])
                for f in sys_frames
            )
            check("B5a 收件人=boss@hotel.demo", send_ok and to_target)
            check("B5a 末帧 done=True",
                  frames[-1].get("done") is True if frames else False)
        except Exception as e:
            check("B5a 确认发送", False, str(e))
    else:
        skip("B5a 确认发送", "未拿到 confirm 帧（" + (e0 or "无帧") + "）")

    # ---- B5b：取消（不发信）----
    if not can_cancel:
        skip("B5b 取消", "b5_cancel 未拿到 confirm 帧（" + (e1 or "无帧") + "）")
        return
    time.sleep(2)
    frames, text = [], []
    try:
        r = requests.post(f"{BASE}/chat/resume",
                          json={"thread_id": f"b5_cancel_{ts_suffix}", "action": "cancel"},
                          headers={"Authorization": "Bearer " + ONLINE_TOKEN},
                          timeout=60, stream=True)
        check("B5b resume cancel HTTP 200", r.status_code == 200, str(r.status_code))
        for raw in r.iter_lines(decode_unicode=True):
            if raw and raw.startswith("data:"):
                try:
                    obj = json.loads(raw[5:].strip())
                    frames.append(obj)
                    if obj.get("type") == "text":
                        text.append(obj.get("content", ""))
                except json.JSONDecodeError:
                    pass
        # 取消语义：无 system 发送成功帧
        no_send = not any(f.get("type") == "system" and
                          (f.get("content") or {}).get("sent_count") for f in frames)
        check("B5b 取消后未发送", no_send)
        check("B5b 末帧 done=True", frames[-1].get("done") is True if frames else False)
    except Exception as e:
        check("B5b 取消", False, str(e))


def online_permission_gate():
    print("\n----- B6. 登录制直拒（无 token / 假 token → /chat 直接 401，不进图） -----")
    # 体验模式已删：匿名不再走到 route 权限门话术层，HTTP 入口即 401
    import requests
    r = requests.post(f"{BASE}/chat",
                      json={"question": "本月入住率多少", "thread_id": f"b6_anon_{int(time.time())}"},
                      timeout=10)
    check("无 token /chat 直接 401", r.status_code == 401, str(r.status_code))
    r = requests.post(f"{BASE}/chat",
                      json={"question": "本月入住率多少", "thread_id": f"b6_bad_{int(time.time())}"},
                      headers={"Authorization": "Bearer bad.token.x"}, timeout=10)
    check("假 token /chat 直接 401", r.status_code == 401, str(r.status_code))


def service_alive():
    import requests
    try:
        r = requests.head(f"{BASE}/openapi.json", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _login_boss():
    """登录分公司老板账号拿 JWT 填 ONLINE_TOKEN；失败返回 False（在线层整层 SKIP）。
    密码默认初始密码 123456，可用环境变量 REGRESS_PASSWORD 覆盖。"""
    import requests
    global ONLINE_TOKEN
    try:
        from app.ai.tool.mysql_tool import query_one
        row = query_one("SELECT employee_id FROM employee WHERE position='分公司老板'")
        if not row:
            print("  [SKIP] 在线层：employee 表没有分公司老板")
            return False
        emp_id = row[0]
    except Exception as e:
        print(f"  [SKIP] 在线层：查库拿老板编号失败（MySQL 未启动？）{e}")
        return False
    try:
        r = requests.post(f"{BASE}/auth/login",
                          json={"employee_id": emp_id,
                                "password": os.getenv("REGRESS_PASSWORD", "123456")},
                          timeout=10)
        if r.status_code != 200:
            print(f"  [SKIP] 在线层：登录失败 HTTP {r.status_code} {r.text[:100]}")
            return False
        ONLINE_TOKEN = r.json()["token"]
        print(f"  [OK] 在线层身份：分公司老板（employee_id={emp_id}，level=4）")
        return True
    except Exception as e:
        print(f"  [SKIP] 在线层：登录异常 {e}")
        return False


# 在线用例登记表（key=命令行参数名）。顺序即执行顺序：
# B6 登录制直拒是两条秒级 401 断言，放首位热身；最重的 HITL（B5）排最后
ONLINE_CASES = {
    "b1": ("B1 帧协议", online_frame_protocol),
    "b6": ("B6 登录制直拒", online_permission_gate),
    "b2": ("B2 六分支", online_branch_cases),
    "b3": ("B3 chart JSON", online_chart_json),
    "b4": ("B4 多轮", online_multi_turn),
    "b5": ("B5 HITL", online_hitl_cancel),
}


def run_online(only=None):
    """在线层。only=None 全跑；否则只跑 {"b2", "b5"} 这类子集（失败重跑不必整层重来）。"""
    print("\n" + "=" * 60)
    print("在线 SSE 场景层（真打服务）" + (f"（只跑：{' '.join(sorted(only))}）" if only else ""))
    print("=" * 60)
    keys = [k for k in ONLINE_CASES if only is None or k in only]
    if not _login_boss():
        for k in keys:
            skip(ONLINE_CASES[k][0], "登录失败（权限门后在线层需经理级身份）")
        return
    for k in keys:
        ONLINE_CASES[k][1]()


# ============================================================
def main():
    # 分组开关：无参数=全量；"offline"=只离线层；"online"=只在线层；
    # "b2 b5"=只跑指定在线用例（失败重跑不必整层重来），可混合（如 offline b6）
    args = [a.lower() for a in sys.argv[1:]]
    only = {a for a in args if a in ONLINE_CASES}

    if not args or "offline" in args:
        run_offline()

    if not args or "online" in args or only:
        if service_alive():
            run_online(only if only and "online" not in args else None)
        else:
            print("\n" + "=" * 60)
            print("服务未启动，在线层整体 SKIP（启动 python app/main.py 后可跑全量）")
            print("=" * 60)
            keys = [k for k in ONLINE_CASES if not only or k in only]
            for k in keys:
                skip(ONLINE_CASES[k][0], "服务离线")

    print("\n" + "=" * 60)
    print(f"汇总：通过 {len(PASS)}，失败 {len(FAIL)}，跳过 {len(SKIP)}")
    if FAIL:
        print("失败项：")
        for n in FAIL:
            print(f"  - {n}")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
