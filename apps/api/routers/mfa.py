import hashlib
import secrets
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
from services.database.models import User
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    get_current_user, create_access_token, create_refresh_token,
    verify_password, create_user_session
)
from apps.api.routers.auth import set_auth_cookies

router = APIRouter(prefix="/api/v1/auth/mfa", tags=["MFA"])

class MFASetupResponse(BaseModel):
    secret: str
    otpauth_url: str

class MFAEnableRequest(BaseModel):
    secret: str
    code: str

class MFAEnableResponse(BaseModel):
    message: str
    recovery_codes: List[str]

class MFAVerifyRequest(BaseModel):
    mfa_ticket: str
    code: str

class MFADisableRequest(BaseModel):
    password: str
    code: str

def generate_mfa_ticket(user_id: str) -> str:
    """Generates a short-lived 5-minute cryptographic ticket for MFA verification challenge."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "token_type": "mfa_challenge",
        "exp": now + timedelta(minutes=5),
        "iat": now
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def decode_mfa_ticket(ticket: str) -> str:
    """Validates MFA challenge ticket and returns user_id."""
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
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA challenge ticket expired or invalid. Please log in again."
        )

@router.post("/setup", response_model=MFASetupResponse)
async def setup_mfa(
    current_user: User = Depends(get_current_user)
):
    """Initiates TOTP multi-factor enrollment by issuing a new cryptographically secure secret."""
    secret = pyotp.random_base32()
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
    """Validates initial TOTP code, enables MFA, and returns 10 single-use recovery codes."""
    totp = pyotp.TOTP(req.secret)
    if not totp.verify(req.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your authenticator app and try again."
        )

    # Generate 10 single-use recovery codes (alphanumeric uppercase)
    raw_recovery_codes = [secrets.token_hex(4).upper() for _ in range(10)]
    hashed_codes = [hashlib.sha256(c.encode("utf-8")).hexdigest() for c in raw_recovery_codes]

    current_user.mfa_secret = req.secret
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
    """Completes login authentication by verifying TOTP code or consuming a recovery code."""
    user_id = decode_mfa_ticket(req.mfa_ticket)
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

    # Check TOTP
    if user.mfa_secret:
        totp = pyotp.TOTP(user.mfa_secret)
        if totp.verify(req.code.strip(), valid_window=1):
            verified = True

    # Check Recovery Codes if TOTP failed
    if not verified and user.mfa_recovery_codes:
        provided_code_clean = req.code.strip().upper()
        h = hashlib.sha256(provided_code_clean.encode("utf-8")).hexdigest()
        if h in user.mfa_recovery_codes:
            verified = True
            used_recovery = True
            # Consume recovery code (single use)
            new_codes = [c for c in user.mfa_recovery_codes if c != h]
            user.mfa_recovery_codes = new_codes
            await db.flush()

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid MFA verification code or recovery code."
        )

    # Issue authenticated session tokens
    access_token = create_access_token({
        "sub": user.id,
        "org_id": user.organization_id,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role)
    })
    refresh_token = create_refresh_token({"sub": user.id})

    # Track enterprise session
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else None)
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
    """Disables MFA after verifying user password and current TOTP code."""
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

    totp = pyotp.TOTP(current_user.mfa_secret)
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
