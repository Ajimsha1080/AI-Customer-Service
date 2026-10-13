import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, Organization, UserRole, Invitation
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_refresh_token_async, revoke_refresh_token,
    get_current_user, generate_oauth_state, verify_oauth_state,
    check_login_lockout, record_failed_login, reset_login_failures
)
from services.security.limiter import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

# Multi-Tenant Architecture Note:
# In this SaaS architecture, user emails are globally unique (`users.email` UNIQUE constraint).
# Each registered user is the OWNER of their newly provisioned tenant organization.
# Users joining existing organizations must do so via cryptographic invitation tokens.

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    organization_name: Optional[str] = None

class AcceptInvitationRequest(BaseModel):
    invitation_token: str
    password: str
    full_name: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    token: str

class GoogleAuthCallbackRequest(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = "http://localhost:3002/auth/callback/google"

def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    is_secure = settings.COOKIE_SECURE or (settings.ENVIRONMENT.lower() in ("production", "prod"))
    cookie_kwargs = {
        "httponly": True,
        "samesite": settings.COOKIE_SAMESITE,
        "secure": is_secure,
    }
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN

    response.set_cookie(key="access_token", value=access_token, max_age=1800, **cookie_kwargs)
    response.set_cookie(key="session_token", value=access_token, max_age=1800, **cookie_kwargs)
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=7*86400, **cookie_kwargs)

def clear_auth_cookies(response: Response) -> None:
    cookie_kwargs = {}
    if settings.COOKIE_DOMAIN:
        cookie_kwargs["domain"] = settings.COOKIE_DOMAIN
    response.delete_cookie(key="access_token", **cookie_kwargs)
    response.delete_cookie(key="session_token", **cookie_kwargs)
    response.delete_cookie(key="refresh_token", **cookie_kwargs)

@router.post("/register")
@limiter.limit("10/minute")
async def register(request: Request, req: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Registers a new tenant. ALWAYS provisions a brand-new Organization with a server-generated slug.
    The creator is designated as the tenant OWNER.
    """
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already registered. Please log in or use another email."
        )

    # Server-generated unique organization slug and ID (String(36) UUID)
    org_name = req.organization_name.strip() if req.organization_name else f"{req.full_name}'s Hospitality"
    base_slug = re.sub(r"[^a-z0-9]+", "-", org_name.lower()).strip("-")[:24] or "hospitality"
    server_generated_slug = f"{base_slug}-{uuid.uuid4().hex[:8]}"

    org_id = str(uuid.uuid4())
    org = Organization(
        id=org_id,
        name=org_name,
        slug=server_generated_slug,
        status="active"
    )
    db.add(org)
    await db.flush()

    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        organization_id=org.id,
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=UserRole.OWNER,
        is_active=True
    )
    db.add(user)
    await db.flush()

    await record_audit_log_async(
        org_id=org.id,
        user_id=user.id,
        action="ORGANIZATION_AND_OWNER_REGISTERED",
        target_type="organization",
        target_id=org.id,
        details={"email": user.email, "slug": org.slug},
        db=db
    )

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role.value if hasattr(user.role, "value") else str(user.role)})
    refresh_token = create_refresh_token({"sub": user.id})

    set_auth_cookies(response, access_token, refresh_token)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value if hasattr(user.role, "value") else str(user.role),
            "organization_id": user.organization_id,
            "organization_slug": org.slug
        }
    }

@router.post("/accept-invitation")
async def accept_invitation(req: AcceptInvitationRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Accepts an organization invitation using a verified token to join an existing tenant."""
    stmt = select(Invitation).where(Invitation.token == req.invitation_token)
    res = await db.execute(stmt)
    inv = res.scalar_one_or_none()

    if not inv:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invitation token."
        )

    if inv.accepted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation token has already been accepted."
        )

    now = datetime.now(timezone.utc)
    # Handle timezone-aware or naive datetime
    inv_expiry = inv.expires_at.replace(tzinfo=timezone.utc) if inv.expires_at.tzinfo is None else inv.expires_at
    if inv_expiry < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation token has expired."
        )

    # Check if user already exists
    stmt_u = select(User).where(User.email == inv.email)
    res_u = await db.execute(stmt_u)
    if res_u.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email {inv.email} already exists."
        )

    assigned_role = UserRole(inv.role) if inv.role in UserRole.__members__ else UserRole.STAFF
    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        organization_id=inv.organization_id,
        email=inv.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=assigned_role,
        is_active=True
    )
    db.add(user)
    inv.accepted_at = now
    await db.flush()

    await record_audit_log_async(
        org_id=inv.organization_id,
        user_id=user.id,
        action="INVITATION_ACCEPTED",
        target_type="user",
        target_id=user.id,
        details={"email": user.email, "role": inv.role},
        db=db
    )

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role.value if hasattr(user.role, "value") else str(user.role)})
    refresh_token = create_refresh_token({"sub": user.id})

    set_auth_cookies(response, access_token, refresh_token)

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

@router.post("/login")
@limiter.limit("30/minute")
async def login(request: Request, req: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    check_login_lockout(req.email)
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        record_failed_login(req.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )

    reset_login_failures(req.email)

    await record_audit_log_async(
        org_id=user.organization_id,
        user_id=user.id,
        action="USER_LOGGED_IN",
        target_type="user",
        target_id=user.id,
        details={"login_type": "password"},
        db=db
    )

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role.value if hasattr(user.role, "value") else str(user.role)})
    refresh_token = create_refresh_token({"sub": user.id})

    set_auth_cookies(response, access_token, refresh_token)

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

@router.get("/google/url")
async def get_google_auth_url(redirect_uri: Optional[str] = "http://localhost:3002/auth/callback/google"):
    """Returns Google OAuth2 authorization URL with cryptographically signed OAuth state."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth SSO is not configured on this server."
        )
    state = generate_oauth_state()
    params = f"client_id={settings.GOOGLE_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=openid%20email%20profile&state={state}"
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return {"auth_url": auth_url, "client_id": settings.GOOGLE_CLIENT_ID, "state": state}

@router.post("/google/callback")
async def google_auth_callback(req: GoogleAuthCallbackRequest, db: AsyncSession = Depends(get_db)):
    """Exchanges Google OAuth authorization code for session tokens with strict token verification."""
    # 0.3 Enforce OAuth state verification against CSRF
    if not req.state or not verify_oauth_state(req.state):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing OAuth state parameter. Request rejected to prevent CSRF."
        )

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth SSO credentials are not configured on this server."
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": req.code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": req.redirect_uri,
                    "grant_type": "authorization_code"
                }
            )
            if token_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to exchange authorization code with Google identity provider."
                )

            token_data = token_res.json()
            access_tok = token_data.get("access_token")
            id_token_jwt = token_data.get("id_token")

            # Verify with Google Userinfo / Tokeninfo
            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_tok}"}
            )
            if user_res.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Failed to retrieve Google user profile."
                )

            uinfo = user_res.json()
            if not uinfo.get("verified_email", False):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Google account email is not verified. Unverified emails cannot authenticate."
                )

            google_email = uinfo.get("email")
            full_name = uinfo.get("name", "Google User")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Google authentication validation failed: {str(e)}"
        )

    # Look up existing user
    stmt = select(User).where(User.email == google_email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"No existing account found for Google email {google_email}. Please register an organization first or accept an invitation."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated."
        )

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role.value if hasattr(user.role, "value") else str(user.role)})
    refresh_token = create_refresh_token({"sub": user.id})

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

@router.post("/logout")
async def logout(req: LogoutRequest, response: Response, db: AsyncSession = Depends(get_db)):
    if req.refresh_token:
        await revoke_refresh_token(req.refresh_token, db=db)
    clear_auth_cookies(response)
    return {"message": "Successfully logged out and token invalidated."}

@router.post("/refresh")
async def refresh(req: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = await decode_refresh_token_async(req.refresh_token, db=db)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found or inactive")

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    new_access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": role_val})
    new_refresh_token = create_refresh_token({"sub": user.id})
    await revoke_refresh_token(req.refresh_token, db=db)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    role_val = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": role_val,
        "organization_id": current_user.organization_id
    }

@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(request: Request, req: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Generates a secure password reset token (timing-safe response)."""
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    reset_token = None
    if user and user.is_active:
        reset_token = create_access_token(
            {"sub": user.id, "email": user.email, "scope": "password_reset"},
            expires_delta=timedelta(hours=1)
        )
        logger.info(f"Password reset token issued for user {user.email}")

    return {
        "message": "If this email exists in our system, a password reset link has been dispatched.",
        "debug_token": reset_token if settings.DEBUG else None
    }

@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Validates reset token and updates account password with Argon2 hash."""
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(req.token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("scope") != "password_reset":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token scope")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = hash_password(req.new_password)
    await db.flush()
    await record_audit_log_async(
        org_id=user.organization_id,
        user_id=user.id,
        action="PASSWORD_RESET_COMPLETED",
        target_type="user",
        target_id=user.id,
        details={"email": user.email},
        db=db
    )
    return {"message": "Password successfully reset. Please log in with your new password."}

@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    """Verifies user email token."""
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(req.token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("scope") != "email_verification":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token scope")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = True
    await db.flush()
    return {"message": "Email address verified successfully. You may now log in."}
