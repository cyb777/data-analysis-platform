# 登录/注册路由：邮箱验证码登录、注册（含验证码发送）。
# 本路由无 prefix，路径就是 /login、/register 等（文件搬家不影响前端）。
import secrets

import redis
from fastapi import APIRouter
from loguru import logger

from app.api.schema.login_schema import (
    SendCodeSchema, LoginSchema, RegisterCodeSchema, RegisterSchema,
)
from app.ai.tool.mysql_tool import query_one, execute_write
from app.ai.tool.send_email_tool import send_email_direct
from app.api.auth import create_token   # 登录/注册成功签发 JWT

# Redis 连接：验证码存这里（带 ex=60 秒过期，自动失效，不用手动清）
redis_conn = redis.Redis(host="127.0.0.1", port=6379, db=0)

auth_router = APIRouter()


def _gen_code() -> str:
    """生成 6 位数字验证码（secrets：验证码属安全场景，不用 random）"""
    return str(secrets.randbelow(900000) + 100000)


@auth_router.post("/send_code")
def send_code(args: SendCodeSchema):
    """登录发码：邮箱已注册才发，验证码存 Redis（key=login:code:{email}，60s）"""
    row = query_one("SELECT id FROM user_info WHERE email=%s", (args.email,))
    if not row:
        return {"code": 500, "msg": "该邮箱未注册，请先注册"}
    # 发码限流：同邮箱 60s 只发一封（setnx 占位，占不到说明 60s 内刚发过）
    if not redis_conn.set(f"login:sendlock:{args.email}", 1, ex=60, nx=True):
        return {"code": 500, "msg": "发送太频繁，请 60 秒后再试"}
    code = _gen_code()
    redis_conn.set(f"login:code:{args.email}", code, ex=60)
    rs = send_email_direct(
        to=args.email,
        subject="登录验证码",
        content=f"您的登录验证码是：{code}，60秒内有效。",
        notification_type="verification",
        trigger_source="verify_code",
    )
    if "失败" in rs:
        return {"code": 500, "msg": "验证码邮件发送失败，请稍后重试"}
    logger.info(f"登录验证码已发送 → {args.email}")
    return {"code": 200, "msg": "验证码已发送，60 秒内有效"}


@auth_router.post("/login")
def login(args: LoginSchema):
    """登录：验 Redis 验证码 → 查 user_info 拿身份 → 签发 JWT（顶层返回 user_id/role/token）"""
    # get(key)：按邮箱取出刚才存的验证码（取不到=没发过/已过期）
    # .decode()：Redis 存的是字节(bytes)，要转成字符串再比对
    code = redis_conn.get(f"login:code:{args.email}")
    if not code or code.decode() != args.code:
        return {"code": 500, "msg": "验证码错误或已过期"}
    # query_one + %s 参数化：pymysql 负责转义，没查到返回 None
    row = query_one("SELECT id, role FROM user_info WHERE email=%s", (args.email,))
    if not row:
        return {"code": 500, "msg": "该邮箱未注册，请先注册"}
    user_id, role = row[0], row[1] or ""
    redis_conn.delete(f"login:code:{args.email}")   # 验证通过即焚毁（防 60s 窗口内重复使用）
    token = create_token(user_id, args.email, role)
    logger.info(f"登录成功 → {args.email} (user_id={user_id})")
    return {"code": 200, "msg": "登录成功",
            "user_id": user_id, "email": args.email, "role": role, "token": token}


@auth_router.post("/register_send_code")
def register_send_code(args: RegisterCodeSchema):
    """注册发码：邮箱未注册才发，验证码存 Redis（key=reg:code:{email}，60s）"""
    if "@" not in args.email:
        return {"code": 400, "msg": "请输入正确的邮箱格式"}
    row = query_one("SELECT id FROM user_info WHERE email=%s", (args.email,))
    if row:
        return {"code": 500, "msg": "该邮箱已注册，请直接登录"}
    # 发码限流：同邮箱 60s 只发一封（setnx 占位，占不到说明 60s 内刚发过）
    if not redis_conn.set(f"reg:sendlock:{args.email}", 1, ex=60, nx=True):
        return {"code": 500, "msg": "发送太频繁，请 60 秒后再试"}
    code = _gen_code()
    redis_conn.set(f"reg:code:{args.email}", code, ex=60)
    rs = send_email_direct(
        to=args.email,
        subject="注册验证码",
        content=f"您的注册验证码是：{code}，60秒内有效。",
        notification_type="verification",
        trigger_source="verify_code",
    )
    if "失败" in rs:
        return {"code": 500, "msg": "验证码邮件发送失败，请稍后重试"}
    logger.info(f"注册验证码已发送 → {args.email}")
    return {"code": 200, "msg": "验证码已发送，60 秒内有效"}


@auth_router.post("/register")
def register(args: RegisterSchema):
    """注册：验码 → 查重 → execute_write 写 user_info → 签发 JWT（顶层返回 user_id/role/token）"""
    code = redis_conn.get(f"reg:code:{args.email}")
    if code is None:
        return {"code": 500, "msg": "验证码已过期，请重新获取"}
    if code.decode() != str(args.code):
        return {"code": 500, "msg": "验证码错误"}
    # 再次查重（防并发：发码后到注册之间同邮箱被别人用了）
    row = query_one("SELECT id FROM user_info WHERE email=%s", (args.email,))
    if row:
        return {"code": 500, "msg": "该邮箱已注册，请直接登录"}
    # execute_write：统一 commit + 返回 lastrowid；user_name 先给默认值，role 用库默认
    user_id = execute_write(
        "INSERT INTO user_info (user_name, email) VALUES (%s, %s)",
        ("user", args.email),
    )
    redis_conn.delete(f"reg:code:{args.email}")   # 用完即焚
    token = create_token(user_id, args.email, "")
    logger.info(f"注册成功 → {args.email} (user_id={user_id})")
    return {"code": 200, "msg": "注册成功",
            "user_id": user_id, "email": args.email, "role": "", "token": token}
