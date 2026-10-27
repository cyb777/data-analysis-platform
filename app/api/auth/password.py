# 密码哈希（PBKDF2-HMAC-SHA256，每人独立随机盐，格式自描述）
# 存储格式：pbkdf2_sha256$迭代数$盐hex$哈希hex
#   ——与 database/seed_hotel.py 的初始账号生成逻辑保持一致（初始密码 123456）
# 用 hashlib 标准库，不引入 passlib 等第三方依赖
import hashlib
import hmac
import os

_ITERATIONS = 100_000


def hash_password(pwd: str, iterations: int = _ITERATIONS) -> str:
    """明文 → 自描述哈希串（每次调用盐不同，同密码结果不同）"""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(pwd: str, stored: str) -> bool:
    """验证明文是否匹配存储哈希；格式异常一律 False（不抛错，按密码错处理）"""
    try:
        _algo, iter_s, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", pwd.encode("utf-8"), bytes.fromhex(salt_hex), int(iter_s))
        # hmac.compare_digest 防时序侧信道（逐字节比较不提前返回）
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False
