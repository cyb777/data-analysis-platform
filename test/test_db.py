"""功能测试：MySQL 工具 / 只读护栏 / data_calc 精确计算（离线，不调大模型）

覆盖：
  - query_all / query_one（tuple / dict 游标、空结果 None）
  - _run_sql 元组格式 + 异常吞成字符串
  - describe_table_tool 正常列 + 非法表名拒绝
  - sql_query_tool 只读护栏（写操作被拒）
  - data_calc_tool 三类精确计算 + 非法 calc_type 被 schema 拒

运行：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def test_query():
    print("\n----- 1. query_all / query_one -----")
    from app.ai.tool.mysql_tool import query_all, query_one

    tables = query_all("SHOW TABLES")
    check("SHOW TABLES 返回 list", isinstance(tables, list))
    check("物理表数量=17（15 业务 + 留痕 + 认证）", len(tables) == 17, str(len(tables)))

    one = query_one("SELECT COUNT(*) AS c FROM stay_record", dict_cursor=True)
    check("query_one dict 游标", isinstance(one, dict) and isinstance(one.get("c"), int), str(one))
    check("stay_record 有数据", one["c"] > 0, str(one["c"]))
    check("查无结果=None", query_one("SELECT employee_id FROM user_info WHERE employee_id=-99999") is None)


def test_query_surface():
    print("\n----- 1b. 可查面=16 张（user_info 纯认证表不在 LLM 视野）-----")
    from app.ai.tool.mysql_tool import sql_query_tool, describe_table_tool

    check("docstring 声明 16 张可查表（describe_table）",
          "可用表名只有这 16 个" in describe_table_tool.description)
    check("两个工具的 docstring 都不含 user_info（模型不知道这张表）",
          "user_info" not in sql_query_tool.description
          and "user_info" not in describe_table_tool.description)
    # 表级硬黑名单：即使 LLM 猜到表名，SELECT/DESCRIBE 都读不到
    check("SELECT user_info 被黑名单硬拦",
          "不在可查范围" in sql_query_tool.invoke({"sql": "SELECT * FROM user_info"}))
    check("DESCRIBE user_info 被黑名单硬拦",
          "不在可查范围" in describe_table_tool.invoke({"table_name": "user_info"}))
    check("黑名单不误伤正常表", "hotel_id" in describe_table_tool.invoke({"table_name": "hotel"}))


def test_run_sql_and_describe():
    print("\n----- 2. _run_sql / describe_table_tool -----")
    from app.ai.tool.mysql_tool import _run_sql, describe_table_tool

    check("_run_sql 元组格式", _run_sql("SELECT 1").startswith("(("))
    check("_run_sql 错误吞成字符串", "查询失败" in _run_sql("SELECT * FROM no_such_table_xx"))

    d = describe_table_tool.invoke({"table_name": "stay_record"})
    check("describe_table 含列", "actual_check_in" in d or "room_amount" in d, d[:60])
    check("describe_table 拒绝非法名",
          "拒绝" in describe_table_tool.invoke({"table_name": "a;drop table"}))


def test_readonly_guard():
    print("\n----- 3. sql_query_tool 只读护栏 -----")
    from app.ai.tool.mysql_tool import sql_query_tool

    blocked = sql_query_tool.invoke({"sql": "DELETE FROM stay_record WHERE stay_id=1"})
    check("写操作被拒", "只读" in blocked or "拒绝" in blocked, str(blocked)[:60])

    # WITH CTE 是只读，必须放行（护栏曾误拦导致邮件写作 agent 取数失败）
    r = sql_query_tool.invoke({"sql": "WITH t AS (SELECT 1 AS x) SELECT * FROM t"})
    check("WITH CTE 放行", "拒绝" not in r and "1" in r, str(r)[:60])


def test_data_calc():
    print("\n----- 4. data_calc_tool 精确计算 -----")
    from app.ai.tool.data_calc_tool import data_calc_tool

    r = data_calc_tool.invoke({"calc_type": "growth_rate", "values": [120, 100]})
    check("growth_rate=20%", "20" in r, r[:60])

    r = data_calc_tool.invoke({"calc_type": "ratio", "values": [25, 100]})
    check("ratio=25%", "25" in r, r[:60])

    r = data_calc_tool.invoke({"calc_type": "compound_growth_rate", "values": [100, 200, 2]})
    check("CAGR≈41.42%", "41.4" in r, r[:60])

    try:
        data_calc_tool.invoke({"calc_type": "plus", "values": [1, 2]})
        check("非法 calc_type 被拒", False)
    except Exception:
        check("非法 calc_type 被拒", True)


def main():
    test_query()
    test_query_surface()
    test_run_sql_and_describe()
    test_readonly_guard()
    test_data_calc()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
