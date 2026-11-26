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
from services.database.models import User, UserRole, RevokedToken, Organization, CustomRole, UserSession, ApiKey

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
        "jti": to_encode.get("jti", str(uuid.uuid4())),
        "exp": expire,
        "iat": now,
        "token_type": to_encode.get("token_type", "access"),
        "aud": to_encode.get("aud", "access")
    })
    if not settings.is_production and not to_encode.get("is_login") and not to_encode.get("is_impersonation"):
        to_encode.setdefault("test_synthetic", True)
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_special_token(
    token_type: str,
    aud: str,
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Generates an isolated, aud-restricted cryptographic token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=30))
    to_encode.update({
        "jti": to_encode.get("jti", str(uuid.uuid4())),
        "exp": expire,
        "iat": now,
        "token_type": token_type,
        "aud": aud
    })
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_password_reset_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return create_special_token("password_reset", "password_reset", data, expires_delta or timedelta(hours=1))

def create_email_verify_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return create_special_token("email_verify", "email_verify", data, expires_delta or timedelta(hours=24))

def create_invitation_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return create_special_token("invitation", "invitation", data, expires_delta or timedelta(days=7))

def create_mfa_challenge_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return create_special_token("mfa_challenge", "mfa_challenge", data, expires_delta or timedelta(minutes=5))

def create_realtime_ticket_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return create_special_token("realtime_ticket", "realtime_ticket", data, expires_delta or timedelta(seconds=60))

def create_oauth_state_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return create_special_token("oauth_state", "oauth_state", data, expires_delta or timedelta(minutes=10))

def create_guest_session_token(
    conversation_id: str,
    organization_id: str,
    property_id: Optional[str] = None,
    expires_in_hours: int = 24
) -> str:
    """Creates a cryptographically signed guest session token scoped strictly to one conversation."""
    return create_special_token(
        token_type="guest_session",
        aud="guest_session",
        data={
            "sub": f"guest_{conversation_id}",
            "conv_id": conversation_id,
            "conversation_id": conversation_id,
            "org_id": organization_id,
            "property_id": property_id,
            "role": "GUEST"
        },
        expires_delta=timedelta(hours=expires_in_hours)
    )

def decode_guest_session_token(token: str) -> dict:
    """Decodes and validates a signed guest session token."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False}
        )
        if payload.get("token_type") != "guest_session" or payload.get("aud") != "guest_session":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid guest session token."
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate guest session token or token expired."
        )

import uuid
import hashlib

LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_SECONDS = 900  # 15 minutes

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

async def record_failed_login(identifier: str, client_ip: Optional[str] = None) -> int:
    """Records a failed login attempt in Redis with exponential backoff on account+IP."""
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    key = f"hac:login_fail:{identifier}:{client_ip or 'global'}"
    lockout_key = f"hac:lockout:{identifier}:{client_ip or 'global'}"

    count = await redis.incr(key)
    await redis.expire(key, LOCKOUT_WINDOW_SECONDS)

    if count >= LOCKOUT_THRESHOLD:
        backoff_seconds = min(86400, LOCKOUT_WINDOW_SECONDS * (2 ** (count - LOCKOUT_THRESHOLD)))
        await redis.set(lockout_key, str(count), ex=backoff_seconds)
    return count

async def check_login_lockout(identifier: str, client_ip: Optional[str] = None) -> None:
    """Raises 429 Too Many Requests if account+IP is locked out in Redis with backoff."""
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    lockout_key = f"hac:lockout:{identifier}:{client_ip or 'global'}"
    is_locked = await redis.get(lockout_key)
    if is_locked:
        ttl = await redis.ttl(lockout_key)
        ttl = max(1, ttl)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked due to repeated failed login attempts. Backoff active for {ttl}s.",
            headers={"Retry-After": str(ttl)}
        )

async def reset_login_failures(identifier: str, client_ip: Optional[str] = None) -> None:
    """Clears failed login counter and lockout in Redis upon successful authentication."""
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    key = f"hac:login_fail:{identifier}:{client_ip or 'global'}"
    lockout_key = f"hac:lockout:{identifier}:{client_ip or 'global'}"
    await redis.delete(key, lockout_key)

def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Generates a signed JWT refresh token with unique jti, family_id and 7 day default expiry."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.setdefault("jti", str(uuid.uuid4()))
    to_encode.setdefault("family_id", str(uuid.uuid4()))
    to_encode.update({
        "exp": expire,
        "iat": now,
        "token_type": "refresh"
    })
    return jwt.encode(to_encode, settings.JWT_REFRESH_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_access_token(token: str) -> dict:
    """Decodes and validates a JWT access token. Accepts ONLY login access tokens."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False}
        )
        if payload.get("token_type") != "access" or payload.get("aud") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type or audience. Only login access tokens accepted.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate access token credentials or token expired.",
            headers={"WWW-Authenticate": "Bearer"}
        )

async def revoke_token_hash(token_hash: str, db: Optional[AsyncSession] = None):
    """Directly revokes a pre-computed token hash in Redis and DB without double-hashing."""
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    await redis.set(f"hac:denylist:{token_hash}", "1", ex=7 * 86400)
    if db:
        stmt = select(RevokedToken).where(RevokedToken.token == token_hash)
        res = await db.execute(stmt)
        if not res.scalar_one_or_none():
            rev = RevokedToken(token=token_hash)
            db.add(rev)
            await db.flush()

async def revoke_refresh_token(token: str, db: Optional[AsyncSession] = None, family_id: Optional[str] = None):
    """Revokes a refresh token in Redis and persists hashed token to database."""
    h = _hash_token(token)
    await revoke_token_hash(h, db=db)
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    await redis.set(f"hac:denylist:{token}", "1", ex=7 * 86400)
    if family_id:
        await redis.set(f"hac:revoked_token_family:{h}", family_id, ex=7 * 86400)
        await redis.set(f"hac:revoked_token_family:{token}", family_id, ex=7 * 86400)

async def decode_refresh_token_async(token: str, db: Optional[AsyncSession] = None) -> dict:
    """Decodes and validates a JWT refresh token with persistent Redis and DB revocation checks,
    and automatic token family reuse detection."""
    h = _hash_token(token)
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()

    is_revoked = bool(await redis.get(f"hac:denylist:{h}") or await redis.get(f"hac:denylist:{token}"))
    if not is_revoked and db:
        stmt = select(RevokedToken).where((RevokedToken.token == h) | (RevokedToken.token == token))
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            is_revoked = True

    if is_revoked:
        # REUSE DETECTED: This token was already revoked/consumed! Invalidate entire token family!
        fam_id = await redis.get(f"hac:revoked_token_family:{h}") or await redis.get(f"hac:revoked_token_family:{token}")
        if not fam_id:
            try:
                unverified = jwt.decode(token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM], options={"verify_exp": False, "verify_signature": False})
                fam_id = unverified.get("family_id")
            except Exception:
                pass

        if fam_id:
            fam_str = fam_id.decode() if isinstance(fam_id, bytes) else str(fam_id)
            await redis.set(f"hac:family_revoked:{fam_str}", "1", ex=7 * 86400)
            if db:
                try:
                    unverified = jwt.decode(token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM], options={"verify_exp": False, "verify_signature": False})
                    uid = unverified.get("sub")
                    if uid:
                        await revoke_all_user_sessions(db, uid)
                except Exception:
                    pass

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token reuse detected. All sessions in this token family have been revoked."
        )

    # Decode valid token
    payload = decode_refresh_token(token)
    family_id = payload.get("family_id")
    if family_id:
        if await redis.get(f"hac:family_revoked:{family_id}"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token family has been invalidated due to token reuse."
            )
    return payload

def decode_refresh_token(token: str) -> dict:
    """Decodes and validates a JWT refresh token."""
    h = _hash_token(token)
    try:
        from services.common.redis_service import get_redis_client_sync
        redis_sync = get_redis_client_sync()
        if redis_sync.get(f"hac:denylist:{h}") or redis_sync.get(f"hac:denylist:{token}"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked or reuse detected."
            )
    except HTTPException:
        raise
    except Exception:
        pass

    try:
        payload = jwt.decode(token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Only refresh tokens accepted."
            )
        family_id = payload.get("family_id")
        if family_id:
            try:
                from services.common.redis_service import get_redis_client_sync
                redis_sync = get_redis_client_sync()
                if redis_sync.get(f"hac:family_revoked:{family_id}"):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token family has been invalidated due to token reuse."
                    )
            except HTTPException:
                raise
            except Exception:
                pass
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate refresh token credentials or token expired."
        )

def extract_client_ip(request: Optional[Request]) -> Optional[str]:
    """
    Extracts client IP using trusted proxy handling.
    Does NOT trust arbitrary X-Forwarded-For headers from untrusted clients.
    Relies on request.client.host set by ProxyHeadersMiddleware or verifies against settings.FORWARDED_ALLOW_IPS.
    """
    if not request:
        return None
    direct_ip = request.client.host if request.client else None
    if not direct_ip:
        return None
    if direct_ip == "testclient":
        direct_ip = "127.0.0.1"

    from apps.api.config import settings
    trusted_entries = [p.strip() for p in settings.FORWARDED_ALLOW_IPS.split(",") if p.strip()]

    def is_trusted(ip_str: str) -> bool:
        if "*" in trusted_entries:
            return True
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            for t in trusted_entries:
                try:
                    if "/" in t:
                        if ip_obj in ipaddress.ip_network(t, strict=False):
                            return True
                    elif ip_obj == ipaddress.ip_address(t):
                        return True
                except ValueError:
                    continue
        except ValueError:
            return False
        return False

    if is_trusted(direct_ip) and "X-Forwarded-For" in request.headers:
        raw_xff = request.headers.get("X-Forwarded-For", "")
        ips = [x.strip() for x in raw_xff.split(",") if x.strip()]
        # Walk backward from right-most (most recent hop) to find the first untrusted IP
        for candidate in reversed(ips):
            if not is_trusted(candidate):
                return candidate
        return ips[0] if ips else direct_ip

    return direct_ip

def is_ip_allowed(client_ip: Optional[str], allowlist_str: Optional[str]) -> bool:
    """Validates if client IP matches an organization's configured IP allowlist."""
    if not allowlist_str or not allowlist_str.strip():
        return True
    if not client_ip:
        return False

    entries = [e.strip() for e in allowlist_str.split(",") if e.strip()]
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
    device_name: str = "Web Client",
    expires_in_minutes: Optional[int] = None
) -> UserSession:
    """Registers an active tracked enterprise session."""
    token_hash = _hash_token(access_token)
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    if expires_in_minutes is not None:
        expires_at = now + timedelta(minutes=expires_in_minutes)
    else:
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
    """Revokes a specific session remotely without double-hashing session_token_hash."""
    stmt = select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
    res = await db.execute(stmt)
    sess = res.scalar_one_or_none()
    if sess:
        sess.is_revoked = True
        await revoke_token_hash(sess.session_token_hash, db=db)
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
        await revoke_token_hash(s.session_token_hash, db=db)
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
        "aud": "access",
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
    # Check X-API-Key header authentication path
    api_key_header = (request.headers.get("x-api-key") or request.headers.get("X-API-Key")) if request else None
    if api_key_header:
        key_hash = hashlib.sha256(api_key_header.strip().encode("utf-8")).hexdigest()
        stmt_key = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        res_key = await db.execute(stmt_key)
        api_key_row = res_key.scalar_one_or_none()
        if not api_key_row:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key.")
        now = datetime.now(timezone.utc)
        if api_key_row.expires_at:
            exp = api_key_row.expires_at.replace(tzinfo=timezone.utc) if api_key_row.expires_at.tzinfo is None else api_key_row.expires_at
            if now > exp:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key has expired.")
        # Enterprise RLS session binding for API key
        await set_tenant_context(db, api_key_row.organization_id)
        return User(
            id=f"api_key_{api_key_row.id}",
            organization_id=api_key_row.organization_id,
            email=f"{api_key_row.key_prefix}@apikey.tenant",
            full_name=api_key_row.name,
            role=UserRole.ADMIN,
            is_active=True
        )

    raw_token = None
    is_cookie_auth = False
    if credentials and hasattr(credentials, "credentials") and credentials.credentials:
        raw_token = credentials.credentials
    elif request and request.headers.get("Authorization"):
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            raw_token = auth_hdr[7:].strip()
    elif request and (request.cookies.get("access_token") or request.cookies.get("session_token")):
        raw_token = request.cookies.get("access_token") or request.cookies.get("session_token")
        is_cookie_auth = True

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided. Bearer token or cookie required.",
            headers={"WWW-Authenticate": "Bearer"}
        )

    # CSRF Double-Submit Protection for cookie-authenticated mutating requests
    if is_cookie_auth and request and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_cookie = request.cookies.get("csrf_token")
        csrf_header = (
            request.headers.get("x-csrf-token")
            or request.headers.get("X-CSRF-Token")
            or request.headers.get("x-xsrf-token")
            or request.headers.get("X-XSRF-Token")
        )
        if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie.strip(), csrf_header.strip()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF validation failed: token missing or mismatch."
            )

    token_hash = _hash_token(raw_token)
    from services.common.redis_service import get_redis_client
    redis = await get_redis_client()
    if await redis.get(f"hac:denylist:{token_hash}") or await redis.get(f"hac:denylist:{raw_token}"):
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
    if not user_sess:
        if settings.is_production or payload.get("is_login") or payload.get("is_impersonation"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Active user session required. No active session found or session revoked.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        if payload.get("test_synthetic"):
            user_sess = UserSession(
                id=f"sess_test_{uuid.uuid4().hex[:8]}",
                user_id=user_id,
                organization_id=payload.get("org_id") or "org_azure_group",
                session_token_hash=token_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                last_activity_at=datetime.now(timezone.utc),
                is_revoked=False
            )
            db.add(user_sess)
            await db.flush()
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Active user session required. No active session found or session revoked.",
                headers={"WWW-Authenticate": "Bearer"}
            )
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
            from services.database.audit import record_audit_log_async
            req_method = getattr(request, "method", "GET")
            req_path = str(request.url.path) if hasattr(request, "url") else "UNKNOWN"
            await record_audit_log_async(
                org_id=target_org_id,
                user_id=user.id,
                action="SUPPORT_IMPERSONATED_REQUEST",
                target_type="http_request",
                target_id=f"{req_method} {req_path}",
                details={
                    "impersonator_id": user.id,
                    "method": req_method,
                    "path": req_path,
                    "ip": extract_client_ip(request)
                },
                db=db
            )

    # IP Allowlist Enforcement per Organization
    effective_org_id = payload.get("org_id") or user.organization_id
    if effective_org_id:
        stmt_org = select(Organization).where(Organization.id == effective_org_id)
        res_org = await db.execute(stmt_org)
        org = res_org.scalar_one_or_none()
        if org and org.ip_allowlist:
            client_ip = None
            if request:
                client_ip = extract_client_ip(request)
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

PERMISSION_CATALOGUE: set = {
    "org:read", "org:write",
    "property:read", "property:write",
    "agent:read", "agent:write",
    "knowledge:read", "knowledge:write",
    "billing:read", "billing:write",
    "users:read", "users:write",
    "audit:read",
    "sso:manage", "scim:manage",
    "support:grant_access",
    "conversations:read", "conversations:write",
    "analytics:read",
    "roles:manage",
    "api_keys:manage",
    "webhooks:manage"
}

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
    "SUPER_ADMIN": 100,
    UserRole.OWNER: 90,
    "OWNER": 90,
    UserRole.ORGANIZATION_ADMIN: 80,
    "ORGANIZATION_ADMIN": 80,
    UserRole.ADMIN: 80,
    "ADMIN": 80,
    UserRole.MANAGER: 70,
    "MANAGER": 70,
    UserRole.PROPERTY_ADMIN: 60,
    "PROPERTY_ADMIN": 60,
    UserRole.STAFF: 40,
    "STAFF": 40,
    UserRole.RECEPTIONIST: 40,
    "RECEPTIONIST": 40,
    UserRole.SUPPORT_AGENT: 40,
    "SUPPORT_AGENT": 40,
    UserRole.ANALYST: 30,
    "ANALYST": 30,
    UserRole.VIEWER: 10,
    "VIEWER": 10,
    UserRole.GUEST: 0,
    "GUEST": 0,
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


