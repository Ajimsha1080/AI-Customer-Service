import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import secrets
from apps.api.config import settings
from services.database.session import get_db, set_tenant_context
from services.database.models import User, UserRole, RevokedToken

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """Hashes a raw password string using Argon2id."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against an Argon2id hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a signed JWT access token with 30 minute default expiry."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": "access"
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

import uuid
import hashlib

LOGIN_FAILURES: Dict[str, list] = {}
LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_SECONDS = 900  # 15 minutes

def record_failed_login(identifier: str) -> int:
    """Records a failed login attempt and returns count of recent failures."""
    now = time.time()
    attempts = [t for t in LOGIN_FAILURES.get(identifier, []) if t > now - LOCKOUT_WINDOW_SECONDS]
    attempts.append(now)
    LOGIN_FAILURES[identifier] = attempts
    return len(attempts)

def check_login_lockout(identifier: str) -> None:
    """Raises 429 Too Many Requests if account has exceeded failed login threshold."""
    now = time.time()
    attempts = [t for t in LOGIN_FAILURES.get(identifier, []) if t > now - LOCKOUT_WINDOW_SECONDS]
    LOGIN_FAILURES[identifier] = attempts
    if len(attempts) >= LOCKOUT_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Account temporarily locked due to repeated failed login attempts. Please try again after 15 minutes."
        )

def reset_login_failures(identifier: str) -> None:
    """Clears failed login attempt counter upon successful authentication."""
    LOGIN_FAILURES.pop(identifier, None)

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a signed JWT refresh token with unique jti and 7 day default expiry."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({
        "jti": str(uuid.uuid4()),
        "exp": expire,
        "iat": now,
        "token_type": "refresh"
    })
    return jwt.encode(to_encode, settings.JWT_REFRESH_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_access_token(token: str) -> dict:
    """Decodes and validates a JWT access token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("token_type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Access token required."
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate access token credentials or token expired.",
            headers={"WWW-Authenticate": "Bearer"}
        )

REFRESH_TOKEN_DENYLIST = set()

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

async def revoke_refresh_token(token: str, db: Optional[AsyncSession] = None):
    """Revokes a refresh token in memory and persists hashed token to database."""
    h = _hash_token(token)
    REFRESH_TOKEN_DENYLIST.add(token)
    REFRESH_TOKEN_DENYLIST.add(h)
    if db:
        stmt = select(RevokedToken).where((RevokedToken.token == h) | (RevokedToken.token == token))
        res = await db.execute(stmt)
        if not res.scalar_one_or_none():
            rev = RevokedToken(token=h)
            db.add(rev)
            await db.flush()

async def decode_refresh_token_async(token: str, db: Optional[AsyncSession] = None) -> dict:
    """Decodes and validates a JWT refresh token with persistent DB revocation and reuse check."""
    h = _hash_token(token)
    if token in REFRESH_TOKEN_DENYLIST or h in REFRESH_TOKEN_DENYLIST:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked or reuse detected."
        )
    if db:
        stmt = select(RevokedToken).where((RevokedToken.token == h) | (RevokedToken.token == token))
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            REFRESH_TOKEN_DENYLIST.add(token)
            REFRESH_TOKEN_DENYLIST.add(h)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked or reuse detected."
            )
    return decode_refresh_token(token)

def decode_refresh_token(token: str) -> dict:
    """Decodes and validates a JWT refresh token."""
    h = _hash_token(token)
    if token in REFRESH_TOKEN_DENYLIST or h in REFRESH_TOKEN_DENYLIST:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked or reuse detected."
        )
    try:
        payload = jwt.decode(token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Refresh token required."
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate refresh token credentials or token expired."
        )

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency: verifies Bearer JWT token and returns authenticated User."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload. Subject missing."
        )

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account associated with this token was not found."
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated."
        )

    # Enterprise RLS session binding
    if user.organization_id:
        await set_tenant_context(db, user.organization_id)

    return user

async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Optional Auth dependency for public endpoints (guest chat / ready checks)."""
    if not credentials or not credentials.credentials:
        return None
    try:
        return await get_current_user(credentials=credentials, db=db)
    except Exception:
        return None

ROLE_HIERARCHY = {
    UserRole.SUPER_ADMIN: 100,
    UserRole.OWNER: 90,
    UserRole.ORGANIZATION_ADMIN: 80,
    UserRole.ADMIN: 80,
    UserRole.PROPERTY_ADMIN: 60,
    UserRole.STAFF: 40,
    UserRole.ANALYST: 30,
    UserRole.VIEWER: 10,
}

def require_role(min_role: UserRole):
    """Enforces minimum role privilege across mutating tenant routes."""
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        user_val = getattr(current_user.role, "value", str(current_user.role))
        min_val = getattr(min_role, "value", str(min_role))
        user_level = ROLE_HIERARCHY.get(user_val, 0)
        required_level = ROLE_HIERARCHY.get(min_val, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {min_val}, caller role: {user_val}."
            )
        return current_user
    return role_checker

async def get_super_admin_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Enforces Super Admin privilege check."""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Platform super admin privileges required."
        )
    return current_user

async def get_current_org_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Enforces Organization Admin/Member level access."""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. User is not assigned to an organization."
        )
    return current_user

def verify_tenant_access(current_user: User, target_org_id: Optional[str]) -> str:
    """Verifies user has permission to access target_org_id.
    Super Admins can access any organization.
    Regular users can only access their own organization_id.
    Zero default fallback to fake or hardcoded organizations.
    """
    if current_user.role == UserRole.SUPER_ADMIN:
        resolved = target_org_id or current_user.organization_id
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization ID must be explicitly specified."
            )
        return resolved

    user_org = current_user.organization_id
    if not user_org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. User has no assigned organization."
        )

    if target_org_id and target_org_id != user_org:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You do not have permission to access another organization's resources."
        )

    return user_org

def generate_oauth_state() -> str:
    """Generates a tamper-proof HMAC-signed OAuth state string."""
    nonce = secrets.token_hex(16)
    exp = int(time.time()) + 600
    payload = {"nonce": nonce, "exp": exp, "action": "google_sso"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

def verify_oauth_state(state: str) -> bool:
    """Verifies HMAC signature and expiration of OAuth state string."""
    if not state:
        return False
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
        return payload.get("action") == "google_sso"
    except Exception:
        return False


