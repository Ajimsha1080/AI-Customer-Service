import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import ipaddress
import secrets
import uuid
import hashlib
from apps.api.config import settings
from services.database.session import get_db, set_tenant_context
from services.database.models import User, UserRole, RevokedToken, Organization, CustomRole, UserSession

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
    """Generates a signed JWT access token with unique jti and 30 minute default expiry."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "jti": str(uuid.uuid4()),
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

def is_ip_allowed(client_ip: Optional[str], allowlist_str: Optional[str]) -> bool:
    """Validates if client IP matches an organization's configured IP allowlist."""
    if not allowlist_str or not allowlist_str.strip():
        return True
    if not client_ip:
        return True
    
    entries = [e.strip() for e in allowlist_str.split(",") if e.strip()]
    if client_ip in ("testclient", "localhost", "127.0.0.1", "::1"):
        if any(e in ("127.0.0.1", "localhost", "testclient", "::1", "127.0.0.0/8") for e in entries):
            return True
        # If allowlist specifies non-local IPs, local test client without allowlist entry is blocked
        return False

    try:
        c_ip = ipaddress.ip_address(client_ip.strip())
    except ValueError:
        return False

    for entry in entries:
        try:
            if "/" in entry:
                if c_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            else:
                if c_ip == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            continue
    return False

async def create_user_session(
    db: AsyncSession,
    user_id: str,
    org_id: str,
    access_token: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    device_name: str = "Web Client"
) -> UserSession:
    """Registers an active tracked enterprise session."""
    token_hash = _hash_token(access_token)
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)  # 24 hour absolute timeout
    session = UserSession(
        id=session_id,
        user_id=user_id,
        organization_id=org_id,
        session_token_hash=token_hash,
        device_name=device_name or "Web Client",
        ip_address=ip_address,
        user_agent=user_agent,
        last_activity_at=now,
        expires_at=expires_at,
        is_revoked=False
    )
    db.add(session)
    await db.flush()
    return session

async def revoke_user_session(db: AsyncSession, session_id: str, user_id: str) -> bool:
    """Revokes a specific session remotely."""
    stmt = select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
    res = await db.execute(stmt)
    sess = res.scalar_one_or_none()
    if sess:
        sess.is_revoked = True
        await revoke_refresh_token(sess.session_token_hash, db=db)
        await db.flush()
        return True
    return False

async def revoke_all_user_sessions(db: AsyncSession, user_id: str, except_token_hash: Optional[str] = None) -> int:
    """Revokes all active sessions for a user, optionally exempting current session."""
    stmt = select(UserSession).where(UserSession.user_id == user_id, UserSession.is_revoked == False)
    if except_token_hash:
        stmt = stmt.where(UserSession.session_token_hash != except_token_hash)
    res = await db.execute(stmt)
    sessions = res.scalars().all()
    count = 0
    for s in sessions:
        s.is_revoked = True
        await revoke_refresh_token(s.session_token_hash, db=db)
        count += 1
    await db.flush()
    return count

def create_impersonation_token(
    admin_user: User,
    target_org_id: str,
    expires_in_minutes: int = 60
) -> str:
    """Issues time-boxed support impersonation token for verified customer support sessions."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expires_in_minutes)
    payload = {
        "sub": admin_user.id,
        "org_id": target_org_id,
        "role": UserRole.OWNER.value,
        "is_impersonation": True,
        "original_user_id": admin_user.id,
        "token_type": "access",
        "exp": expire,
        "iat": now
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency: verifies Bearer JWT token, active status, session revocation, IP allowlist, and support impersonation."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    raw_token = credentials.credentials
    token_hash = _hash_token(raw_token)
    if raw_token in REFRESH_TOKEN_DENYLIST or token_hash in REFRESH_TOKEN_DENYLIST:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    payload = decode_access_token(raw_token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload. Subject missing."
        )

    # Session Lifecycle & Idle Timeout Enforcement
    stmt_sess = select(UserSession).where(UserSession.session_token_hash == token_hash)
    res_sess = await db.execute(stmt_sess)
    user_sess = res_sess.scalar_one_or_none()
    if user_sess:
        if user_sess.is_revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session has been revoked.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        now = datetime.now(timezone.utc)
        exp = user_sess.expires_at.replace(tzinfo=timezone.utc) if user_sess.expires_at.tzinfo is None else user_sess.expires_at
        if now > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired (absolute timeout).",
                headers={"WWW-Authenticate": "Bearer"}
            )
        last_act = user_sess.last_activity_at.replace(tzinfo=timezone.utc) if user_sess.last_activity_at.tzinfo is None else user_sess.last_activity_at
        if (now - last_act).total_seconds() > 3600:  # 60 minute idle timeout
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired due to inactivity.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        user_sess.last_activity_at = now

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

    # Impersonation Verification & Audit Banner Injection
    if payload.get("is_impersonation"):
        target_org_id = payload.get("org_id")
        stmt_org = select(Organization).where(Organization.id == target_org_id)
        res_org = await db.execute(stmt_org)
        target_org = res_org.scalar_one_or_none()
        if not target_org or not target_org.support_access_granted_until:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer has not granted active support access to this organization."
            )
        now = datetime.now(timezone.utc)
        supp_exp = target_org.support_access_granted_until.replace(tzinfo=timezone.utc) if target_org.support_access_granted_until.tzinfo is None else target_org.support_access_granted_until
        if supp_exp < now:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Customer support access has expired."
            )
        if request:
            request.state.is_support_impersonation = True

    # IP Allowlist Enforcement per Organization
    effective_org_id = payload.get("org_id") or user.organization_id
    if effective_org_id:
        stmt_org = select(Organization).where(Organization.id == effective_org_id)
        res_org = await db.execute(stmt_org)
        org = res_org.scalar_one_or_none()
        if org and org.ip_allowlist:
            client_ip = None
            if request:
                client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else None)
            if client_ip and not is_ip_allowed(client_ip, org.ip_allowlist):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. IP address {client_ip} is not in the organization's allowlist."
                )

    # Enterprise RLS session binding
    if effective_org_id:
        await set_tenant_context(db, effective_org_id)

    return user

async def get_optional_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Optional Auth dependency for public endpoints (guest chat / ready checks)."""
    if not credentials or not credentials.credentials:
        return None
    try:
        return await get_current_user(request=request, credentials=credentials, db=db)
    except Exception:
        return None

ROLE_PERMISSIONS: Dict[str, set] = {
    "SUPER_ADMIN": {"*"},
    "OWNER": {
        "org:read", "org:write", "property:read", "property:write", "agent:read", "agent:write",
        "knowledge:read", "knowledge:write", "billing:read", "billing:write", "users:read", "users:write",
        "audit:read", "sso:manage", "scim:manage", "support:grant_access", "conversations:read",
        "conversations:write", "analytics:read", "roles:manage", "api_keys:manage", "webhooks:manage"
    },
    "ORGANIZATION_ADMIN": {
        "org:read", "org:write", "property:read", "property:write", "agent:read", "agent:write",
        "knowledge:read", "knowledge:write", "billing:read", "users:read", "users:write",
        "audit:read", "sso:manage", "scim:manage", "conversations:read", "conversations:write",
        "analytics:read", "roles:manage", "api_keys:manage", "webhooks:manage"
    },
    "ADMIN": {
        "org:read", "property:read", "property:write", "agent:read", "agent:write",
        "knowledge:read", "knowledge:write", "billing:read", "users:read", "users:write",
        "audit:read", "conversations:read", "conversations:write", "analytics:read"
    },
    "PROPERTY_ADMIN": {
        "property:read", "property:write", "agent:read", "agent:write",
        "knowledge:read", "knowledge:write", "users:read", "conversations:read",
        "conversations:write", "analytics:read"
    },
    "STAFF": {
        "property:read", "agent:read", "knowledge:read", "conversations:read", "conversations:write"
    },
    "ANALYST": {
        "property:read", "analytics:read", "audit:read", "conversations:read"
    },
    "VIEWER": {
        "property:read", "knowledge:read", "conversations:read"
    }
}

async def get_user_permissions(user: User, db: AsyncSession) -> set:
    """Resolves granular permissions for user including custom roles."""
    if user.role == UserRole.SUPER_ADMIN:
        return {"*"}
    role_key = user.role.value if hasattr(user.role, "value") else str(user.role)
    perms = set(ROLE_PERMISSIONS.get(role_key, set()))
    if user.custom_role_id:
        stmt = select(CustomRole).where(CustomRole.id == user.custom_role_id)
        res = await db.execute(stmt)
        custom = res.scalar_one_or_none()
        if custom and custom.permissions:
            perms.update(custom.permissions)
    return perms

def require_permission(permission: str):
    """Enforces fine-grained enterprise permission check."""
    async def permission_checker(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ) -> User:
        user_perms = await get_user_permissions(current_user, db)
        if "*" in user_perms or permission in user_perms:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required permission: {permission}."
        )
    return permission_checker

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


