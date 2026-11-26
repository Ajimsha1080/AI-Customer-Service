import re
import time
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, Organization, UserRole, Invitation, SSOConfig, RevokedToken
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    create_password_reset_token, revoke_all_user_sessions,
    decode_refresh_token_async, revoke_refresh_token,
    get_current_user, generate_oauth_state, verify_oauth_state,
    check_login_lockout, record_failed_login, reset_login_failures,
    create_user_session, ROLE_HIERARCHY, extract_client_ip
)
from services.security.limiter import limiter
from services.security.password_policy import validate_password_policy
from services.security.email_service import email_service

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
    validate_password_policy(req.password)
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
        is_active=True,
        email_verified=False
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

    validate_password_policy(req.password)

    # C3: Re-verify role against tenant allowlist and inviter role hierarchy
    from apps.api.routers.organizations import ALLOWED_TENANT_ASSIGNABLE_ROLES
    target_role_str = inv.role.upper().strip()
    if target_role_str not in ALLOWED_TENANT_ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid tenant role in invitation: '{inv.role}'. Permitted roles are: {sorted(ALLOWED_TENANT_ASSIGNABLE_ROLES)}"
        )

    if inv.invited_by_user_id:
        stmt_inviter = select(User).where(User.id == inv.invited_by_user_id)
        res_inviter = await db.execute(stmt_inviter)
        inviter = res_inviter.scalar_one_or_none()
        if not inviter or not inviter.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inviting user account is inactive or not found."
            )
        inviter_role_val = inviter.role.value if hasattr(inviter.role, "value") else str(inviter.role)
        inviter_rank = ROLE_HIERARCHY.get(inviter_role_val, 0)
        target_rank = ROLE_HIERARCHY.get(target_role_str, 0)
        if inviter_rank <= target_rank:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Inviter ({inviter_role_val}) no longer outranks the invited role ({target_role_str})."
            )

    assigned_role = UserRole(target_role_str)
    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        organization_id=inv.organization_id,
        email=inv.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=assigned_role,
        is_active=True,
        email_verified=True
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
    client_ip = extract_client_ip(request)
    await check_login_lockout(req.email, client_ip)
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        await record_failed_login(req.email, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )

    # Check Organization-Enforced SSO Policy
    if user.organization_id:
        stmt_sso = select(SSOConfig).where(SSOConfig.organization_id == user.organization_id)
        res_sso = await db.execute(stmt_sso)
        sso_cfg = res_sso.scalar_one_or_none()
        if sso_cfg and sso_cfg.enforce_sso:
            user_domain = user.email.split("@")[1].lower() if "@" in user.email else ""
            if not sso_cfg.domains or user_domain in [d.lower() for d in sso_cfg.domains]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="SSO_REQUIRED: Password login is disabled for your organization. Please log in using SSO."
                )

    # Multi-Factor Authentication Challenge
    mfa_required = bool(user.mfa_enabled)
    if user.role == UserRole.SUPER_ADMIN:
        mfa_required = True
    elif not mfa_required and user.organization_id:
        stmt_org = select(Organization).where(Organization.id == user.organization_id)
        res_org = await db.execute(stmt_org)
        org = res_org.scalar_one_or_none()
        if org and org.mfa_enforced:
            mfa_required = True

    if mfa_required:
        from apps.api.routers.mfa import generate_mfa_ticket
        ticket = generate_mfa_ticket(user.id)
        return {
            "mfa_required": True,
            "mfa_ticket": ticket,
            "user_id": user.id,
            "message": "Multi-factor authentication required. Please verify with your authenticator code or recovery code."
        }

    await reset_login_failures(req.email, client_ip)

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
async def refresh(req: RefreshTokenRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Rotates refresh token on every use, detecting token reuse and revoking the family."""
    payload = await decode_refresh_token_async(req.refresh_token, db=db)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User account not found or inactive")

    family_id = payload.get("family_id") or str(uuid.uuid4())

    # 1. Immediately revoke the presented refresh token and associate with family
    await revoke_refresh_token(req.refresh_token, db=db, family_id=family_id)

    # 2. Issue new access token + new rotated refresh token with the same family_id
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    new_access_token = create_access_token({
        "sub": user.id,
        "org_id": user.organization_id,
        "role": role_val,
        "is_login": True
    })
    new_refresh_token = create_refresh_token({"sub": user.id, "family_id": family_id})

    # 3. Create active session row for new access token
    client_ip = extract_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    await create_user_session(
        db=db,
        user_id=user.id,
        org_id=user.organization_id,
        access_token=new_access_token,
        ip_address=client_ip,
        user_agent=user_agent
    )

    set_auth_cookies(response, new_access_token, new_refresh_token)

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
    """Generates a secure password reset token (timing-safe response with anti-enumeration protection)."""
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    reset_token = None
    if user and user.is_active:
        jti = str(uuid.uuid4())
        reset_token = create_password_reset_token(
            {"sub": user.id, "email": user.email, "jti": jti},
            expires_delta=timedelta(hours=1)
        )
        await email_service.send_email(
            to_email=user.email,
            subject="Security Notice: Reset Your Password",
            template_name="password_reset",
            template_context={
                "name": user.full_name,
                "reset_url": f"http://localhost:3002/reset-password?token={reset_token}"
            }
        )
    else:
        # Anti-enumeration timing mitigation: constant-time dummy hashing work
        hash_password("timing_safe_dummy_constant_for_enumeration_defense")

    return {
        "message": "If this email exists in our system, a password reset link has been dispatched.",
        "debug_token": reset_token if settings.DEBUG else None
    }

@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(request: Request, req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Validates reset token, enforces single-use invalidation, revokes all sessions, and updates password."""
    from jose import jwt, JWTError
    validate_password_policy(req.new_password)
    try:
        payload = jwt.decode(
            req.token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_aud": False}
        )
        if payload.get("token_type") != "password_reset" or payload.get("aud") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type or audience for password reset."
            )
        user_id = payload.get("sub")
        jti = payload.get("jti")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token")

    if not jti:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset token missing jti.")

    # 1. Single-use check: Redis & DB RevokedToken
    jti_key = f"reset_jti:{jti}"
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()

    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3)
        ok = await r.set(jti_key, "1", nx=True, ex=3600)
        await r.aclose()
        if not ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset token has already been used.")
    except HTTPException:
        raise
    except Exception:
        pass

    stmt_rev = select(RevokedToken).where(
        (RevokedToken.token == jti_key) | 
        (RevokedToken.token == token_hash) | 
        (RevokedToken.token == req.token)
    )
    res_rev = await db.execute(stmt_rev)
    if res_rev.scalars().first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset token has already been used or revoked.")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = hash_password(req.new_password)
    # Record token as revoked for single-use guarantee
    db.add(RevokedToken(token=jti_key))
    db.add(RevokedToken(token=token_hash))

    # C5: Revoke all active user sessions and refresh tokens on password reset
    await revoke_all_user_sessions(db=db, user_id=user.id)
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
    """Verifies user email token with single-use invalidation."""
    from jose import jwt, JWTError
    try:
        payload = jwt.decode(req.token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("scope") != "email_verification":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token scope")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    stmt_rev = select(RevokedToken).where((RevokedToken.token == token_hash) | (RevokedToken.token == req.token))
    res_rev = await db.execute(stmt_rev)
    if res_rev.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token has already been used or revoked.")

    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.is_active = True
    user.email_verified = True
    db.add(RevokedToken(token=token_hash))
    await db.flush()
    return {"message": "Email address verified successfully. You may now log in."}
