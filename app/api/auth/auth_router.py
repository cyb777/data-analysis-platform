# 账号接口：登录（员工编号+密码）/ 改密码 / 绑定邮箱
#
# 设计要点：
#   ① 无公开注册——账号随员工数据预置（user_info 纯认证表，初始密码 123456）；
#   ② 登录校验 user_info.password_hash（PBKDF2），身份档案（姓名/职位/级别/邮箱）
#      一律以 employee 表为准，登录时 JOIN 一次带出并签入 JWT（level）；
#   ③ 改密码 / 绑邮箱要求携带 JWT（get_required_user），操作的是"自己"这一行。
import re

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from app.api.auth.jwt import create_token, get_required_user
from app.api.auth.password import hash_password, verify_password
from app.api.schema.login_schema import BindEmailSchema, ChangePasswordSchema, LoginSchema
from app.ai.tool.mysql_tool import execute_write, query_one

auth_router = APIRouter(prefix="/auth", tags=["账号"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@auth_router.post("/login", summary="员工编号+密码登录")
def login(body: LoginSchema):
    # ① 认证表查密码哈希（user_info 不进 LLM 查询清单，但应用层照常访问）
    row = query_one(
        "SELECT u.password_hash, e.employee_name, e.position, e.level, e.employee_status "
        "FROM user_info u JOIN employee e ON e.employee_id = u.employee_id "
        "WHERE u.employee_id = %s", (body.employee_id,))
    if row is None:
        raise HTTPException(status_code=401, detail="编号或密码错误")
    pwd_hash, emp_name, position, level, status = row
    # ② 验密（错误提示不区分编号不存在/密码错，防枚举）
    if not verify_password(body.password, pwd_hash):
        raise HTTPException(status_code=401, detail="编号或密码错误")
    if status != "在职":
        raise HTTPException(status_code=403, detail="该员工已离职，账号已停用")

    token = create_token(employee_id=body.employee_id, level=level, password_hash=pwd_hash)
    logger.info(f"登录成功：{emp_name}({body.employee_id}) position={position} level={level}")
    return {
        "message": "登录成功",
        "employee_id": body.employee_id,
        "employee_name": emp_name,
        "position": position,
        "level": level,
        "token": token,
    }


@auth_router.post("/change_password", summary="修改自己的密码（需登录）")
def change_password(body: ChangePasswordSchema, auth: dict = Depends(get_required_user)):
    emp_id = auth["user_id"]
    row = query_one("SELECT password_hash FROM user_info WHERE employee_id=%s", (emp_id,))
    if row is None or not verify_password(body.old_password, row[0]):
        raise HTTPException(status_code=400, detail="原密码错误")
    # 改密后旧 token 天然失效——token 里的 pwd_sig 与库中新哈希失配即 401，
    # 无需吊销动作
    execute_write("UPDATE user_info SET password_hash=%s WHERE employee_id=%s",
                  (hash_password(body.new_password), emp_id))
    logger.info(f"员工 {emp_id} 修改密码成功，旧 token 随哈希变更自然失效")
    return {"message": "密码修改成功，其他登录态已失效，请使用新密码重新登录"}


@auth_router.post("/bind_email", summary="绑定/更改自己的收邮件邮箱（需登录）")
def bind_email(body: BindEmailSchema, auth: dict = Depends(get_required_user)):
    emp_id = auth["user_id"]
    email = body.email.strip()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    # UNIQUE 约束兜底，但提前查一遍给出友好提示
    owner = query_one("SELECT employee_id FROM employee WHERE email=%s", (email,))
    if owner is not None and owner[0] != emp_id:
        raise HTTPException(status_code=400, detail="该邮箱已被其他员工绑定")
    execute_write("UPDATE employee SET email=%s WHERE employee_id=%s", (email, emp_id))
    logger.info(f"员工 {emp_id} 绑定邮箱 {email}")
    return {"message": f"邮箱绑定成功：{email}"}
