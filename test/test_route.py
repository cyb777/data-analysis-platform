"""功能测试：路由 Schema / 结构约束 / 权限门行为（离线，不调大模型、不启服务）

覆盖：
  - Route 结构化 Schema：Literal 6 分支合法值 + 脏值拦截
  - 收件人提取归邮件侧（route 只判分支+改写+权限门，无关键词兜底/纠偏层）
  - 权限门行为（mock LLM 输出）：db/chart/system 均要经理级 level>=3，
    普通员工/匿名越权 → route="end" 自写 answer 直连 END；rag/chat/clarify 全员放行

运行：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_route.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def test_route_schema():
    print("\n----- 1. Route 结构化 Schema（Literal 6 分支）-----")
    from pydantic import ValidationError
    from app.ai.schemas.llm_route_schema import Route

    for b in ("rag", "db", "chart", "clarify", "system", "chat"):
        r = Route(branch=b, rewritten_q="x")
        check(f"合法分支 {b}", r.branch == b)

    # compare 已随 v1.5.6 删除，不再是合法分支
    try:
        Route(branch="compare", rewritten_q="x")
        check("已删分支 compare 被拒", False)
    except ValidationError:
        check("已删分支 compare 被拒", True)

    # 模型脑抽的脏值必须被拦下
    try:
        Route(branch="think", rewritten_q="x")
        check("脏值 think 被拦截", False)
    except ValidationError:
        check("脏值 think 被拦截", True)


def test_recipient_role():
    print("\n----- 2. 收件人提取归邮件侧（route 只判分支+改写+权限门） -----")
    from app.ai.schemas.llm_route_schema import Route
    import app.ai.nodes.route as r

    check("Route schema 不含 recipient_role（route 不提取收件人）",
          "recipient_role" not in Route.model_fields)
    check("route 无明文岗位词表（_SYSTEM_RECIPIENT_ROLES 已删）",
          not hasattr(r, "_SYSTEM_RECIPIENT_ROLES"))
    check("route 无关键词兜底/纠偏层（LLM 语义主判，异常走 chat 安全分支）",
          not hasattr(r, "_fallback_route") and not hasattr(r, "_is_system_intent"))


def test_permission_gate():
    print("\n----- 3. 权限门行为（mock LLM 输出：db/chart/system 均要经理级 level>=3） -----")
    from unittest.mock import patch
    from langchain_core.runnables import RunnableLambda
    from app.ai.schemas.llm_route_schema import Route
    import app.ai.nodes.route as r

    def fake_llm(branch):
        """替身 LLM：with_structured_output 返回固定分支的 Route（RunnableLambda 接 | 管道）"""
        fake = type("FakeLLM", (), {})()
        fake.with_structured_output = lambda schema: RunnableLambda(
            lambda _in: Route(branch=branch, rewritten_q="x"))
        return fake

    def run(branch, level=None):
        state = {"question": "q", "history": [], "summary_upto": 0,
                 "compressed_summary": "", "memory_facts": []}
        if level is not None:
            state["user_level"] = level
        with patch.object(r, "_llm", fake_llm(branch)):
            return r.route_node(state)

    # 经理级（level>=3）放行：route=原分支、不带 answer
    for b in ("db", "chart", "system"):
        out = run(b, level=3)
        check(f"经理级放行 {b}", out.get("route") == b and not out.get("answer"),
              str(out.get("route")))

    # 普通员工（level=1）越权：route="end" + 自写 answer（话术按分支区分）
    for b, what in (("db", "数据查询"), ("chart", "数据查询"), ("system", "邮件发送")):
        out = run(b, level=1)
        check(f"普通员工 {b} 被拦（route=end + 无{what}权限话术）",
              out.get("route") == "end" and f"无{what}权限" in out.get("answer", ""),
              str(out.get("route")))

    # 匿名：user_level 键缺省 / =0 都拦
    check("匿名（无 user_level 键）拦 system", run("system").get("route") == "end")
    check("匿名 level=0 拦 db", run("db", level=0).get("route") == "end")

    # rag/chat/clarify 不受权限门限制（业务学习全员开放）
    for b in ("rag", "chat", "clarify"):
        check(f"{b} 匿名放行", run(b).get("route") == b)


def main():
    test_route_schema()
    test_recipient_role()
    test_permission_gate()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
