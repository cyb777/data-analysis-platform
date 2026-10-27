"""功能测试：员工编号登录（编号+密码）/ 改密码 / 绑邮箱 / JWT 签发解签 + 鉴权边界

离线：用 FastAPI TestClient 走真实 HTTP 层，但不触发 lifespan（不建图、不调大模型）。
MySQL 未启动时，依赖真库的 login/change_password/bind_email 分支自动 SKIP。

运行：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_auth.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL, SKIP = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def skip(name, reason=""):
    SKIP.append(name)
    print(f"[SKIP] {name}" + (f" -> {reason}" if reason else ""))


def test_jwt():
    print("\n----- 1. JWT 签发 / 解签 -----")
    from app.api.auth import create_token
    from app.api.auth.jwt import _decode as decode_token

    token = create_token(employee_id=2020000101, level=4)
    payload = decode_token(token)
    check("user_id / level 正确",
          payload["user_id"] == 2020000101 and payload["level"] == 4, str(payload))
    check("payload 不含 email/role（新契约）",
          "email" not in payload and "role" not in payload)
    check("含过期时间 exp", "exp" in payload)


def test_secret_failfast():
    print("\n----- 1b. JWT_SECRET 未配置 fail-fast（assert_secret_configured） -----")
    import app.api.auth.jwt as j

    # 现状（.env 已配强随机）调用不抛
    try:
        j.assert_secret_configured()
        check("现状 JWT_SECRET 已配置（不抛）", True)
    except RuntimeError as e:
        check("现状 JWT_SECRET 已配置（不抛）", False, str(e))

    # 模拟"仍是内置默认值"的环境：启动即拒（RuntimeError）
    orig = j.JWT_SECRET
    try:
        j.JWT_SECRET = j._DEV_DEFAULT_SECRET
        try:
            j.assert_secret_configured()
            check("默认值密钥启动即拒（RuntimeError）", False)
        except RuntimeError:
            check("默认值密钥启动即拒（RuntimeError）", True)
    finally:
        j.JWT_SECRET = orig


def test_password_module():
    print("\n----- 1c. password.py PBKDF2（roundtrip / 自描述格式 / 防时序） -----")
    from app.api.auth.password import hash_password, verify_password

    h1, h2 = hash_password("123456"), hash_password("123456")
    check("自描述格式 pbkdf2_sha256$迭代数$盐$哈希",
          h1.startswith("pbkdf2_sha256$") and len(h1.split("$")) == 4, h1.split("$")[0])
    check("roundtrip：正确密码验真", verify_password("123456", h1) is True)
    check("roundtrip：错误密码验假", verify_password("wrong", h1) is False)
    check("独立盐（同密码两次哈希不同）", h1 != h2)
    check("畸形存储串验假不炸", verify_password("123456", "not-a-valid-hash") is False)


def test_login_schema():
    print("\n----- 2. 登录/账号入参 Schema 校验（Pydantic）-----")
    from pydantic import ValidationError
    from app.api.schema.login_schema import BindEmailSchema, ChangePasswordSchema, LoginSchema

    s = LoginSchema(employee_id=2020000101, password="123456")
    check("LoginSchema 合法入参", s.employee_id == 2020000101)
    c = ChangePasswordSchema(old_password="123456", new_password="abc123")
    check("ChangePasswordSchema 合法入参", c.new_password == "abc123")
    b = BindEmailSchema(email="t@t.com")
    check("BindEmailSchema 合法入参", b.email == "t@t.com")
    try:
        LoginSchema(employee_id=2020000101)   # 缺 password
        check("缺 password 字段被拦", False)
    except ValidationError:
        check("缺 password 字段被拦", True)
    try:
        ChangePasswordSchema(old_password="1", new_password="123")   # 新密码 <6 位
        check("新密码过短被拦", False)
    except ValidationError:
        check("新密码过短被拦", True)


def test_http_guard():
    print("\n----- 3. HTTP 鉴权边界（TestClient，不跑 lifespan）-----")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.api.auth import create_token

    # 在 app 上临时挂一个强制登录的测试路由，验证 get_required_user 的 401/200 边界。
    from fastapi import Depends
    from app.api.auth.jwt import get_required_user

    @fastapi_app.get("/_test_auth_only")
    def _auth_only(user=Depends(get_required_user)):
        return {"code": 200, "user_id": user["user_id"]}

    client = TestClient(fastapi_app)
    auth = {"Authorization": "Bearer " + create_token(employee_id=1, level=4)}

    r = client.get("/_test_auth_only")
    check("强制登录路由 无 token 401", r.status_code == 401, str(r.status_code))
    r = client.get("/_test_auth_only", headers={"Authorization": "Bearer bad.token.x"})
    check("强制登录路由 假 token 401", r.status_code == 401, str(r.status_code))
    r = client.get("/_test_auth_only", headers=auth)
    check("强制登录路由 真 token 200",
          r.status_code == 200 and r.json().get("code") == 200, str(r.status_code))


def test_account_endpoints():
    print("\n----- 4. login / change_password / bind_email（真库，DB 挂则 SKIP）-----")
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    client = TestClient(fastapi_app)
    try:
        from app.ai.tool.mysql_tool import execute_write, query_one
        boss = query_one(
            "SELECT employee_id, employee_name, email FROM employee WHERE position='分公司老板'")
        if boss is None:
            skip("账号接口分支", "employee 表没有分公司老板")
            return
        emp_id, emp_name, origin_email = boss
    except Exception as e:
        skip("账号接口分支", f"MySQL 不可用：{e}")
        return

    # ---------- 登录 ----------
    r = client.post("/auth/login", json={"employee_id": emp_id, "password": "123456"})
    ok = (r.status_code == 200 and r.json().get("token")
          and r.json().get("level") == 4 and r.json().get("employee_name") == emp_name)
    check("登录成功（编号+初始密码，level=4）", ok, f"{r.status_code} {r.json()}")
    token = r.json().get("token", "")
    auth = {"Authorization": "Bearer " + token}

    r = client.post("/auth/login", json={"employee_id": emp_id, "password": "wrong_pass"})
    check("错误密码 401", r.status_code == 401, str(r.status_code))
    r = client.post("/auth/login", json={"employee_id": 9999999999, "password": "123456"})
    check("不存在编号 401", r.status_code == 401, str(r.status_code))

    # ---------- 无 token 的鉴权边界 ----------
    r = client.post("/auth/change_password", json={"old_password": "a", "new_password": "abcdef"})
    check("改密码 无 token 401", r.status_code == 401, str(r.status_code))
    r = client.post("/auth/bind_email", json={"email": "x@x.com"})
    check("绑邮箱 无 token 401", r.status_code == 401, str(r.status_code))

    # ---------- 绑邮箱闭环（finally 恢复原邮箱，不污染种子数据）----------
    try:
        r = client.post("/auth/bind_email", json={"email": "boss_test@hotel.demo"}, headers=auth)
        check("绑邮箱成功", r.status_code == 200, f"{r.status_code} {r.json()}")
        row = query_one("SELECT email FROM employee WHERE employee_id=%s", (emp_id,))
        check("库中邮箱已更新", row and row[0] == "boss_test@hotel.demo", str(row))
        # 冲突：绑别人的邮箱应 400（注意 pymysql 里 LIKE 的 % 要写成 %%，这里直接不用 LIKE）
        other = query_one(
            "SELECT email FROM employee WHERE email IS NOT NULL AND employee_id<>%s LIMIT 1",
            (emp_id,))
        if other:
            r = client.post("/auth/bind_email", json={"email": other[0]}, headers=auth)
            check("绑别人已用邮箱 400（UNIQUE）", r.status_code == 400, str(r.status_code))
        r = client.post("/auth/bind_email", json={"email": "not-an-email"}, headers=auth)
        check("邮箱格式错误 400", r.status_code == 400, str(r.status_code))
    finally:
        execute_write("UPDATE employee SET email=%s WHERE employee_id=%s", (origin_email, emp_id))
    row = query_one("SELECT email FROM employee WHERE employee_id=%s", (emp_id,))
    check("原邮箱已恢复", row and row[0] == origin_email, str(row))

    # ---------- 改密码闭环（finally 改回 123456）----------
    try:
        r = client.post("/auth/change_password",
                        json={"old_password": "123456", "new_password": "newpass888"}, headers=auth)
        check("改密码成功", r.status_code == 200, f"{r.status_code} {r.json()}")
        # 改密后旧 token 立即失效（pwd_sig 与库中现值失配 → 401）
        r = client.post("/auth/bind_email", json={"email": "boss_test@hotel.demo"}, headers=auth)
        check("改密后旧 token 401", r.status_code == 401, str(r.status_code))
        r = client.post("/auth/login", json={"employee_id": emp_id, "password": "123456"})
        check("旧密码已失效 401", r.status_code == 401, str(r.status_code))
        r = client.post("/auth/login", json={"employee_id": emp_id, "password": "newpass888"})
        new_token = r.json().get("token", "")
        check("新密码可登录", r.status_code == 200 and bool(new_token), str(r.status_code))
        # 旧 token 已被吊销，后续操作须用新 token
        r = client.post("/auth/change_password",
                        json={"old_password": "bad_old", "new_password": "xxx999"},
                        headers={"Authorization": "Bearer " + new_token})
        check("原密码错误 400", r.status_code == 400, str(r.status_code))
    finally:
        from app.api.auth.password import hash_password
        execute_write("UPDATE user_info SET password_hash=%s WHERE employee_id=%s",
                      (hash_password("123456"), emp_id))
    r = client.post("/auth/login", json={"employee_id": emp_id, "password": "123456"})
    check("初始密码已恢复可登录", r.status_code == 200, str(r.status_code))


def main():
    test_jwt()
    test_secret_failfast()
    test_password_module()
    test_login_schema()
    test_http_guard()
    test_account_endpoints()

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项，跳过 {len(SKIP)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
