"""认证服务 - 使用 bcrypt 直接加密（兼容 bcrypt>=4.1）"""
from app.models import User
from app.models.misc import AuditLog
import bcrypt
from datetime import datetime, timedelta
from jose import jwt, JWTError
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from sqlalchemy.orm import Session
from fastapi import Request


def hash_password(password: str) -> str:
    """使用bcrypt进行密码哈希"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_current_user(request: Request, db: Session) -> User | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    user = db.query(User).filter(User.id == payload.get("user_id")).first()
    return user


def check_role(user: User, allowed_roles: list) -> bool:
    if not user:
        return False
    return user.role in allowed_roles


def log_audit(db: Session, user_id: int, username: str, action: str,
              target_type: str = None, target_id: int = None,
              detail: str = None, ip: str = None, company_id: int = None):
    log = AuditLog(
        company_id=company_id,
        user_id=user_id,
        username=username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=ip,
    )
    db.add(log)
    db.commit()
