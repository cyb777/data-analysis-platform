"""登录鉴权层：邮箱验证码登录 / 注册。

验证码写入 Redis（带过期时间），登录发码走 SystemAgent（校验邮箱是否存在并发送），
注册流程保留直接发信逻辑。
"""
import random

import redis
from fastapi import APIRouter, Request
from loguru import logger

from app.api.schema.login_schema import (
    SendCodeSchema, LoginSchema, RegisterCodeSchema, RegisterSchema,
)
from app.ai.tool.mysql_tool import mysql_tool
from app.ai.tool.send_email_tool import send_email
from app.ai.agent.system_agent import SystemAgent

# Redis 连接：验证码就存这里（复用全局 Redis 实例）
# 为什么验证码存 Redis？——带过期时间(ex=60秒)，自动失效，不用手动清
redis_conn = redis.Redis(host="127.0.0.1", port=6379, db=0)
system_router = APIRouter()
system_agent = SystemAgent()   # 登录验证码智能体（单例）


@system_router.post("/send_code")
def send_code(request: Request, args: SendCodeSchema):
    """登录：SystemAgent 查邮箱是否注册 + 发验证码（验证码代码生成传入，保证确定性）"""
    code = str(random.randint(100000, 999999))
    rs = system_agent.answer(args.email, code)
    if rs["code"] != 200:
        return {"code": rs["code"], "msg": rs.get("msg", "邮箱不存在或发送失败")}
    # set(key, value, ex=60)：把验证码存进 Redis，60秒后自动删除
    # key 格式 login:code:邮箱，value 是验证码 → 登录时按邮箱取出来比对
    redis_conn.set(f"login:code:{args.email}", code, ex=60)   # 以接口生成的码为准（邮件里也是它）
    logger.info(f"登录验证码已发送 → {args.email}")
    return {"code": 200, "msg": "验证码已发送"}


@system_router.post("/login")
def login(args: LoginSchema):
    """登录：校验验证码"""
    # get(key)：从 Redis 按邮箱取出刚才存的验证码（取不到=没发过/已过期）
    # .decode()：Redis 存的是字节(bytes)，要转成字符串再比对
    code = redis_conn.get(f"login:code:{args.email}")
    if code and code.decode() == args.code:
        logger.info(f"登录成功 → {args.email}")
        return {"code": 200, "msg": "登录成功"}
    return {"code": 500, "msg": "验证码错误或已过期"}


@system_router.post("/register_send_code")
def register_send_code(args: RegisterCodeSchema):
    """注册：向邮箱发验证码"""
    if "@" not in args.email:
        return {"code": 400, "msg": "请输入正确的邮箱格式"}
    code = str(random.randint(100000, 999999))
    redis_conn.set(f"reg:code:{args.email}", code, ex=60)
    # send_email.invoke：直接调用发邮件工具（三个参数按 EmailSchema 的结构传）
    send_email.invoke({"to": args.email, "subject": "注册验证码", "content": f"您的注册验证码是：{code}，60秒内有效。"})
    logger.info(f"注册验证码已发送 → {args.email}")
    return {"code": 200, "msg": "验证码已发送至邮箱"}


@system_router.post("/register")
def register(args: RegisterSchema):
    """注册：校验验证码 + 查重 + 写入 user_info 表"""
    code = redis_conn.get(f"reg:code:{args.email}")
    if code is None:
        return {"code": 500, "msg": "验证码已过期，请重新获取"}
    if code.decode() != str(args.code):
        return {"code": 500, "msg": "验证码错误"}

    # 查重：user_info 表里有没有这个邮箱
    result = mysql_tool.invoke({"sql": f"SELECT * FROM user_info WHERE email='{args.email}'"})
    if result and "查询失败" not in result and result != "()" and result != "[]":
        return {"code": 500, "msg": "用户已注册"}

    # 写入 user_info 表
    mysql_tool.invoke({"sql": f"INSERT INTO user_info(user_name, email) VALUES('user', '{args.email}')"})
    redis_conn.delete(f"reg:code:{args.email}")
    logger.info(f"注册成功 → {args.email}")
    return {"code": 200, "msg": "注册成功"}
