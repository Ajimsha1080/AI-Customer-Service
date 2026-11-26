import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import pyotp
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, UserRole
from services.database.audit import record_audit_log_async
from services.security.encryption import encrypt_value, decrypt_value
from services.common.redis_service import get_redis_client_sync
from apps.api.auth import (
    get_current_user, create_access_token, create_refresh_token,
    verify_password, hash_password, create_user_session, extract_client_ip
)
from apps.api.routers.auth import set_auth_cookies

logger = logging.getLogger("hospitality_agent_cloud.routers.mfa")

router = APIRouter(prefix="/api/v1/auth/mfa", tags=["MFA"])

class MFASetupResponse(BaseModel):
    secret: str
    otpauth_url: str

class MFAEnableRequest(BaseModel):
    code: str
    password: Optional[str] = None
    secret: Optional[str] = None  # Deprecated client-sent secret; server-side pending secret is preferred

class MFAEnableResponse(BaseModel):
    message: str
    recovery_codes: List[str]

class MFAVerifyRequest(BaseModel):
    mfa_ticket: str
    code: str

class MFADisableRequest(BaseModel):
    password: str
    code: str

def _redis():
    try:
        return get_redis_client_sync()
    except Exception:
        return None

def generate_mfa_ticket(user_id: str) -> str:
    """Generates a short-lived 5-minute cryptographic ticket for MFA verification challenge with jti."""
    now = datetime.now(timezone.utc)
    jti = f"mfajti_{uuid.uuid4().hex}"
    payload = {
        "sub": user_id,
        "jti": jti,
        "token_type": "mfa_challenge",
        "exp": now + timedelta(minutes=5),
        "iat": now
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_mfa_ticket_payload(ticket: str) -> dict:
    """Validates MFA challenge ticket and returns full payload."""
    try:
        payload = jwt.decode(ticket, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("token_type") != "mfa_challenge":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid challenge token type."
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ticket subject.")
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA challenge ticket expired or invalid. Please log in again."
        )

def decode_mfa_ticket(ticket: str) -> str:
    """Validates MFA challenge ticket and returns user_id."""
    return decode_mfa_ticket_payload(ticket)["sub"]

@router.post("/setup", response_model=MFASetupResponse)
async def setup_mfa(
    current_user: User = Depends(get_current_user)
):
    """Initiates TOTP multi-factor enrollment by issuing and storing a server-side pending secret."""
    secret = pyotp.random_base32()
    
    # Store pending secret securely server-side in Redis with 15-minute expiration
    r = _redis()
    if r:
        try:
            r.setex(f"hac:mfa_pending:{current_user.id}", 900, secret)
        except Exception as e:
            if settings.is_production:
                raise RuntimeError(f"Failed to store pending MFA secret in Redis: {e}")

    totp = pyotp.TOTP(secret)
    otpauth_url = totp.provisioning_uri(
        name=current_user.email,
        issuer_name="Enterprise AI Concierge"
    )
    return {"secret": secret, "otpauth_url": otpauth_url}

@router.post("/enable", response_model=MFAEnableResponse)
async def enable_mfa(
    req: MFAEnableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Re-authenticates user password, validates server-side pending TOTP, blocks code reuse,
    and returns 10 single-use >=80-bit Argon2-hashed recovery codes."""
    # 1. Re-authentication check
    if req.password:
        if not verify_password(req.password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect password for MFA enrollment re-authentication."
            )
    elif settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password re-authentication is required to enable MFA in production."
        )

    # 2. Retrieve server-side pending secret (do not trust client-sent secret)
    r = _redis()
    pending_secret = None
    if r:
        try:
            val = r.get(f"hac:mfa_pending:{current_user.id}")
            if val:
                pending_secret = val.decode("utf-8") if isinstance(val, bytes) else val
        except Exception:
            pass

    secret_to_use = pending_secret
    if not secret_to_use:
        # In non-production tests that mock setup, allow fallback to req.secret if provided
        if not settings.is_production and req.secret:
            secret_to_use = req.secret
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="MFA enrollment not initiated or expired. Please call /setup first."
            )

    # 3. Block TOTP code reuse
    code_clean = req.code.strip()
    if r:
        try:
            if r.exists(f"hac:totp_used:{current_user.id}:{code_clean}"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="TOTP code has already been used. Please wait for the next time window."
                )
        except HTTPException:
            raise
        except Exception:
            pass

    # 4. Verify TOTP code
    totp = pyotp.TOTP(secret_to_use)
    if not totp.verify(code_clean, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your authenticator app and try again."
        )

    # Cleanup pending secret
    if r:
        try:
            r.delete(f"hac:mfa_pending:{current_user.id}")
        except Exception:
            pass

    # 5. Generate 10 single-use recovery codes with >= 80 bits of entropy, Argon2-hashed
    # 10 bytes = 80 bits -> 20 hex characters formatted as 5 blocks of 4
    raw_recovery_codes = []
    hashed_codes = []
    for _ in range(10):
        token_hex = secrets.token_hex(10).upper()  # 80 bits
        formatted_code = f"{token_hex[:4]}-{token_hex[4:8]}-{token_hex[8:12]}-{token_hex[12:16]}-{token_hex[16:20]}"
        raw_recovery_codes.append(formatted_code)
        hashed_codes.append(hash_password(formatted_code))

    current_user.mfa_secret = encrypt_value(secret_to_use, org_id=current_user.organization_id)
    current_user.mfa_enabled = True
    current_user.mfa_recovery_codes = hashed_codes
    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="MFA_ENABLED",
        target_type="user",
        target_id=current_user.id,
        details={"method": "TOTP"},
        db=db
    )

    return {
        "message": "Multi-factor authentication successfully enabled. Store these recovery codes securely.",
        "recovery_codes": raw_recovery_codes
    }

@router.post("/verify")
async def verify_mfa_login(
    req: MFAVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Completes login authentication with ticket locking after 5 failures, per-account rate limiting,
    TOTP code reuse blocking, and Argon2 recovery code verification."""
    ticket_payload = decode_mfa_ticket_payload(req.mfa_ticket)
    user_id = ticket_payload["sub"]
    ticket_jti = ticket_payload.get("jti", user_id)

    # Rate limiting & ticket locking check
    r = _redis()
    if r:
        try:
            ticket_attempts = int(r.get(f"hac:mfa_ticket_attempts:{ticket_jti}") or 0)
            account_attempts = int(r.get(f"hac:mfa_account_attempts:{user_id}") or 0)
            if ticket_attempts >= 5 or account_attempts >= 5:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="MFA challenge locked: maximum 5 failed attempts exceeded. Please log in again."
                )
        except HTTPException:
            raise
        except Exception:
            pass

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account invalid or deactivated."
        )

    verified = False
    used_recovery = False
    code_clean = req.code.strip().upper()

    # 1. Check TOTP
    if user.mfa_secret:
        # Block code reuse
        if r and r.exists(f"hac:totp_used:{user.id}:{code_clean}"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TOTP code has already been used. Please wait for the next time window."
            )
        raw_secret = decrypt_value(user.mfa_secret, org_id=user.organization_id)
        totp = pyotp.TOTP(raw_secret)
        if totp.verify(code_clean, valid_window=1):
            verified = True
            if r:
                try:
                    r.setex(f"hac:totp_used:{user.id}:{code_clean}", 90, "1")
                except Exception:
                    pass

    # 2. Check Recovery Codes (Argon2-hashed) if TOTP failed
    if not verified and user.mfa_recovery_codes:
        matched_hash = None
        for h in user.mfa_recovery_codes:
            # Check Argon2 match (or legacy SHA256 fallback during transition)
            if verify_password(code_clean, h) or hashlib.sha256(code_clean.encode("utf-8")).hexdigest() == h:
                matched_hash = h
                break
        if matched_hash:
            verified = True
            used_recovery = True
            new_codes = [c for c in user.mfa_recovery_codes if c != matched_hash]
            user.mfa_recovery_codes = new_codes
            await db.flush()

    # Handle verification failure: record attempt and lock ticket if attempts >= 5
    if not verified:
        if r:
            try:
                t_att = r.incr(f"hac:mfa_ticket_attempts:{ticket_jti}")
                r.expire(f"hac:mfa_ticket_attempts:{ticket_jti}", 300)
                a_att = r.incr(f"hac:mfa_account_attempts:{user.id}")
                r.expire(f"hac:mfa_account_attempts:{user.id}", 300)
                if t_att >= 5 or a_att >= 5:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="MFA challenge locked: maximum 5 failed attempts exceeded. Please log in again."
                    )
            except HTTPException:
                raise
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA verification code or recovery code."
        )

    # Success: clear failure counters
    if r:
        try:
            r.delete(f"hac:mfa_ticket_attempts:{ticket_jti}")
            r.delete(f"hac:mfa_account_attempts:{user.id}")
        except Exception:
            pass

    # Issue authenticated session tokens
    access_token = create_access_token({
        "sub": user.id,
        "org_id": user.organization_id,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role)
    })
    refresh_token = create_refresh_token({"sub": user.id})

    # Track enterprise session
    client_ip = extract_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    await create_user_session(
        db=db,
        user_id=user.id,
        org_id=user.organization_id,
        access_token=access_token,
        ip_address=client_ip,
        user_agent=user_agent
    )

    set_auth_cookies(response, access_token, refresh_token)

    await record_audit_log_async(
        org_id=user.organization_id,
        user_id=user.id,
        action="USER_LOGGED_IN",
        target_type="user",
        target_id=user.id,
        details={"login_type": "mfa", "used_recovery_code": used_recovery},
        db=db
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "organization_id": user.organization_id
        }
    }

@router.post("/disable")
async def disable_mfa(
    req: MFADisableRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Disables MFA after verifying user password and current TOTP code.
    MFA is strictly MANDATORY for SUPER_ADMIN accounts and cannot be disabled."""
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA is mandatory for Super Admin accounts and cannot be disabled."
        )

    if not verify_password(req.password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password."
        )

    if not current_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled on this account."
        )

    raw_secret = decrypt_value(current_user.mfa_secret, org_id=current_user.organization_id)
    totp = pyotp.TOTP(raw_secret)
    if not totp.verify(req.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP verification code."
        )

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_recovery_codes = []
    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="MFA_DISABLED",
        target_type="user",
        target_id=current_user.id,
        details={},
        db=db
    )

    return {"message": "MFA has been successfully disabled."}
