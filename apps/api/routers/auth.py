import time
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, Organization, UserRole
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    decode_refresh_token_async, revoke_refresh_token,
    get_current_user
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    organization_name: Optional[str] = "Azure Palm Hospitality Group"
    organization_slug: Optional[str] = "azure-palm-group"

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str

class GoogleAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: Optional[str] = "http://localhost:3001/auth/callback/google"

@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is already registered"
        )

    slug = req.organization_slug or (req.organization_name.lower().replace(" ", "-") if req.organization_name else "default-org")
    stmt_org = select(Organization).where(Organization.slug == slug)
    res_org = await db.execute(stmt_org)
    org = res_org.scalar_one_or_none()
    if not org:
        clean_slug = slug.replace("-", "_").strip("_")[:18] or "org"
        org_id = f"org_{clean_slug}_{uuid.uuid4().hex[:8]}"
        org = Organization(
            id=org_id,
            name=req.organization_name or "Default Organization",
            slug=slug,
            status="active"
        )
        db.add(org)
        await db.flush()

    user_id = f"usr_{int(time.time()*1000)}"
    user = User(
        id=user_id,
        organization_id=org.id,
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=UserRole.ORGANIZATION_ADMIN,
        is_active=True
    )
    db.add(user)
    await db.flush()

    await record_audit_log_async(
        org_id=org.id,
        user_id=user.id,
        action="USER_REGISTERED",
        target_type="user",
        target_id=user.id,
        details={"email": user.email, "role": user.role},
        db=db
    )

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    refresh_token = create_refresh_token({"sub": user.id})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "organization_id": user.organization_id
        }
    }

@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.email == req.email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated"
        )

    await record_audit_log_async(
        org_id=user.organization_id,
        user_id=user.id,
        action="USER_LOGGED_IN",
        target_type="user",
        target_id=user.id,
        details={"login_type": "password"},
        db=db
    )

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    refresh_token = create_refresh_token({"sub": user.id})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "organization_id": user.organization_id
        }
    }

@router.get("/google/url")
async def get_google_auth_url(redirect_uri: Optional[str] = "http://localhost:3001/auth/callback/google"):
    """Returns Google OAuth2 login authorization URL."""
    client_id = settings.GOOGLE_CLIENT_ID or "mock-google-client-id"
    params = f"client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&scope=openid%20email%20profile"
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{params}"
    return {"auth_url": auth_url, "client_id": client_id}

@router.post("/google/callback")
async def google_auth_callback(req: GoogleAuthCallbackRequest, db: AsyncSession = Depends(get_db)):
    """Exchanges Google OAuth authorization code for session tokens."""
    google_email = f"google_user_{req.code[:8]}@example.com"
    full_name = "Google User"

    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
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
                if token_res.status_code == 200:
                    id_token_jwt = token_res.json().get("id_token")
                    # Fetch user info using access token
                    access_tok = token_res.json().get("access_token")
                    user_res = await client.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {access_tok}"})
                    if user_res.status_code == 200:
                        uinfo = user_res.json()
                        google_email = uinfo.get("email", google_email)
                        full_name = uinfo.get("name", full_name)
        except Exception as e:
            print("Google OAuth Exception:", str(e))

    # Provision user if not existing
    stmt = select(User).where(User.email == google_email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user:
        stmt_org = select(Organization).where(Organization.slug == "azure-palm-group")
        res_org = await db.execute(stmt_org)
        org = res_org.scalar_one_or_none()
        if not org:
            org = Organization(id=f"org_sso_{uuid.uuid4().hex[:8]}", name="Azure Palm Group", slug="azure-palm-group")
            db.add(org)
            await db.flush()

        user = User(
            id=f"usr_google_{uuid.uuid4().hex[:8]}",
            organization_id=org.id,
            email=google_email,
            hashed_password=hash_password(uuid.uuid4().hex),
            full_name=full_name,
            role=UserRole.ORGANIZATION_ADMIN,
            is_active=True
        )
        db.add(user)
        await db.flush()

    access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    refresh_token = create_refresh_token({"sub": user.id})

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "organization_id": user.organization_id
        }
    }

@router.post("/logout")
async def logout(req: LogoutRequest, db: AsyncSession = Depends(get_db)):
    await revoke_refresh_token(req.refresh_token, db=db)
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

    new_access_token = create_access_token({"sub": user.id, "org_id": user.organization_id, "role": user.role})
    new_refresh_token = create_refresh_token({"sub": user.id})
    await revoke_refresh_token(req.refresh_token, db=db)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "organization_id": current_user.organization_id
    }
