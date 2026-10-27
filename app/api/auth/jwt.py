# JWT 签发与校验（HS256 + 7 天过期）。
# 两级校验：
#   get_optional_user  → 内部 helper：无 token 返回 None（登录制下端点不直接用它）
#   get_required_user  → 所有业务接口用：无 token 直接 401（登录制，无体验模式）
# 注意：/chat 现用 fetch 手写 SSE（可自定义请求头），token 走标准
#   Authorization: Bearer；query param 仅作兼容保留。
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request
from loguru import logger

from app.ai.tool.mysql_tool import query_one

# 默认值仅作本地开发兜底；生产必须 .env 覆盖，lifespan 启动时 fail-fast 校验
_DEV_DEFAULT_SECRET = "dev-only-secret-change-me-in-prod"
JWT_SECRET = os.getenv("JWT_SECRET", _DEV_DEFAULT_SECRET)
JWT_ALG = "HS256"
JWT_EXPIRE_DAYS = 7


def assert_secret_configured() -> None:
    """S3 启动 fail-fast：JWT_SECRET 仍是内置默认值时拒绝起服务。

    由 main.py lifespan 调用——uvicorn 真正启动必过此关；
    裸 TestClient / 单测 import 不跑 lifespan，回归不受影响。
    """
    if JWT_SECRET == _DEV_DEFAULT_SECRET:
        raise RuntimeError(
            "JWT_SECRET 未配置（仍是内置开发默认值），拒绝启动。"
            "请在 .env 中设置强随机 JWT_SECRET。"
        )


def _pwd_sig(password_hash: str) -> str:
    """密码哈希指纹：PBKDF2 哈希本身高熵盐化，sha256 截断 16 hex 作派生签名，
    不增加实际攻击面。改密 → 哈希变 → 指纹变 → 旧 token 天然失配。"""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_token(employee_id: int, level: int = 1, password_hash: str = "") -> str:
    """签发 JWT：登录成功后调用。
    payload 只留 employee_id(user_id 键名沿用) + level，
    不再放 email/role——邮箱只是收信地址不是身份，职位级别以 employee 表为准；
    level 签进 token：权限门/邮件工具分级直接读 token，不为每轮聊天查库；
    代价是级别调整后要重新登录才生效（token 是登录时快照）。
    pwd_sig 为签发时密码哈希的指纹，验签时与库中当前哈希比对——
    改密后旧 token 一律 401，无需吊销清单/额外组件。password_hash 缺省则不含
    pwd_sig（测试/工具签发），验签时跳过库比对。
    """
    payload = {
        "user_id": employee_id,
        "level": level,
        "iat": time.time(),
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    if password_hash:
        payload["pwd_sig"] = _pwd_sig(password_hash)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _extract_token(request: Request) -> str:
    """从 Authorization: Bearer 取 token；query param 仅作兼容保留"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


def _decode(token: str) -> dict:
    """解出 token payload 并过 S2 密码指纹比对；过期/无效/已吊销抛 401"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="token 无效")
    # 带 pwd_sig 的 token（登录签发）与库中当前密码哈希比对——
    # 改密后哈希变、指纹失配 → 旧 token 一律 401；用户被删同样拒。
    # 无 pwd_sig 的 token（测试签发/部署前存量）跳过库比对，7 天自然过期。
    sig = payload.get("pwd_sig")
    if sig is not None:
        row = query_one("SELECT password_hash FROM user_info WHERE employee_id=%s",
                        (payload.get("user_id", 0),))
        if row is None or _pwd_sig(row[0]) != sig:
            raise HTTPException(status_code=401, detail="登录态已失效，请重新登录")
    return payload


def get_optional_user(request: Request) -> dict | None:
    """内部 helper：无 token → None；有 token → 必须合法，否则 401。
    校验通过后，调用方必须用返回的身份【覆盖】query param 里自报的 user_id/email
    ——身份以 token 为准，客户端自报的不信。
    """
    token = _extract_token(request)
    if not token:
        return None
    user = _decode(token)
    logger.info(f"JWT 校验通过 → 员工编号 {user.get('user_id')} (level={user.get('level')})")
    return user


def get_required_user(request: Request) -> dict:
    """强制登录接口用：无 token 或 token 非法 → 401"""
    user = get_optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user
