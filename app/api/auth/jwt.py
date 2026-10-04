# JWT 签发与校验（HS256 + 7 天过期）。
# 两级校验：
#   get_optional_user  → /chat 用：无 token 走「体验模式」，有 token 必须合法
#   get_required_user  → 强制登录接口用：无 token 直接 401
# 注意：/chat 现用 fetch 手写 SSE（可自定义请求头），token 走标准
#   Authorization: Bearer；query param 仅作兼容保留。
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request
from loguru import logger

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me-in-prod")
JWT_ALG = "HS256"
JWT_EXPIRE_DAYS = 7


def create_token(user_id: int, email: str, role: str) -> str:
    """签发 JWT：登录/注册成功后调用"""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _extract_token(request: Request) -> str:
    """从 Authorization: Bearer 取 token；query param 仅作兼容保留"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token", "")


def _decode(token: str) -> dict:
    """解出 token payload；过期/无效抛 401"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="token 无效")


def get_optional_user(request: Request) -> dict | None:
    """/chat 用：无 token → None（体验模式）；有 token → 必须合法，否则 401。
    校验通过后，调用方必须用返回的身份【覆盖】query param 里自报的 user_id/email
    ——身份以 token 为准，客户端自报的不信。
    """
    token = _extract_token(request)
    if not token:
        return None
    user = _decode(token)
    logger.info(f"JWT 校验通过 → {user.get('email')} (user_id={user.get('user_id')})")
    return user


def get_required_user(request: Request) -> dict:
    """强制登录接口用：无 token 或 token 非法 → 401"""
    user = get_optional_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录")
    return user
