# auth 领域包：JWT 工具（jwt.py）+ 验证码登录/注册路由（auth_router.py）
# 对外保持 from app.api.auth import create_token / get_optional_user / get_required_user 可用
from app.api.auth.jwt import create_token, get_optional_user, get_required_user
