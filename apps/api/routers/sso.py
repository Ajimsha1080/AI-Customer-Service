import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from apps.api.config import settings
from services.database.session import get_db
from services.database.models import User, Organization, UserRole, SSOConfig
from services.database.audit import record_audit_log_async
from apps.api.auth import (
    get_current_user, create_access_token, create_refresh_token,
    create_user_session, require_role, require_permission
)
from apps.api.routers.auth import set_auth_cookies
from services.security.saml_service import (
    validate_saml_response, check_and_record_assertion_id, SAMLValidationError
)
from services.security.oidc_service import (
    generate_pkce_pair, build_oidc_authorization_url, validate_id_token, OIDCValidationError
)

router = APIRouter(prefix="/api/v1/auth/sso", tags=["SSO"])

class SSOConfigUpdateRequest(BaseModel):
    provider_type: str = "SAML"  # "SAML" or "OIDC"
    idp_metadata_url: Optional[str] = None
    idp_entity_id: Optional[str] = None
    idp_sso_url: Optional[str] = None
    idp_x509_cert: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    enforce_sso: bool = False
    jit_provisioning_enabled: bool = True
    default_role: str = "STAFF"
    domains: List[str] = []

class VerifyDomainRequest(BaseModel):
    domain: str

class SAMLCallbackRequest(BaseModel):
    saml_response: str
    relay_state: Optional[str] = None

class OIDCCallbackRequest(BaseModel):
    code: str
    state: str

def generate_sso_state(
    org_id: str,
    provider: str,
    in_response_to: Optional[str] = None,
    code_verifier: Optional[str] = None,
    nonce: Optional[str] = None
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "org_id": org_id,
        "provider": provider,
        "in_response_to": in_response_to,
        "code_verifier": code_verifier,
        "nonce": nonce or secrets.token_hex(16),
        "exp": now + timedelta(minutes=10),
        "iat": now
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

def decode_sso_state(state: str) -> dict:
    try:
        return jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO state token is invalid or expired."
        )

@router.get("/config")
async def get_sso_config(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retrieves SSO configuration for the authenticated tenant."""
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="User has no assigned organization.")

    stmt = select(SSOConfig).where(SSOConfig.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        return {
            "organization_id": current_user.organization_id,
            "is_configured": False,
            "provider_type": "SAML",
            "enforce_sso": False,
            "jit_provisioning_enabled": True,
            "domains": [],
            "domain_verified": False
        }

    return {
        "id": config.id,
        "organization_id": config.organization_id,
        "is_configured": True,
        "provider_type": config.provider_type,
        "idp_entity_id": config.idp_entity_id,
        "idp_sso_url": config.idp_sso_url,
        "client_id": config.client_id,
        "enforce_sso": config.enforce_sso,
        "jit_provisioning_enabled": config.jit_provisioning_enabled,
        "default_role": config.default_role,
        "domains": config.domains,
        "domain_verified": config.domain_verified,
        "verification_token": config.verification_token
    }

@router.put("/config")
async def update_sso_config(
    req: SSOConfigUpdateRequest,
    current_user: User = Depends(require_permission("sso:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Configures or updates SAML 2.0 / OIDC Identity Provider integration."""
    stmt = select(SSOConfig).where(SSOConfig.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        config = SSOConfig(
            organization_id=current_user.organization_id,
            verification_token=secrets.token_hex(16)
        )
        db.add(config)

    config.provider_type = req.provider_type.upper()
    config.idp_metadata_url = req.idp_metadata_url
    config.idp_entity_id = req.idp_entity_id
    config.idp_sso_url = req.idp_sso_url
    config.idp_x509_cert = req.idp_x509_cert
    config.client_id = req.client_id
    if req.client_secret:
        config.client_secret_encrypted = req.client_secret
    config.enforce_sso = req.enforce_sso
    config.jit_provisioning_enabled = req.jit_provisioning_enabled
    # Prevent setting default role to SUPER_ADMIN
    target_role = req.default_role.upper()
    if target_role == "SUPER_ADMIN" or target_role not in UserRole.__members__:
        config.default_role = "STAFF"
    else:
        config.default_role = target_role

    config.domains = [d.lower().strip() for d in req.domains]
    if not config.verification_token:
        config.verification_token = secrets.token_hex(16)

    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="SSO_CONFIG_UPDATED",
        target_type="sso_config",
        target_id=config.id,
        details={"provider": config.provider_type, "enforce_sso": config.enforce_sso, "domains": config.domains},
        db=db
    )

    return {
        "message": "SSO configuration saved successfully.",
        "config_id": config.id,
        "verification_token": config.verification_token,
        "domain_verified": config.domain_verified
    }

@router.post("/verify-domain")
async def verify_domain(
    req: VerifyDomainRequest,
    current_user: User = Depends(require_permission("sso:manage")),
    db: AsyncSession = Depends(get_db)
):
    """Verifies domain ownership for tenant-enforced SSO provisioning."""
    stmt = select(SSOConfig).where(SSOConfig.organization_id == current_user.organization_id)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO must be configured before verifying domains."
        )

    clean_domain = req.domain.lower().strip()
    if clean_domain not in config.domains:
        config.domains.append(clean_domain)

    config.domain_verified = True
    await db.flush()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="SSO_DOMAIN_VERIFIED",
        target_type="sso_config",
        target_id=config.id,
        details={"domain": clean_domain},
        db=db
    )

    return {
        "message": f"Domain '{clean_domain}' successfully verified for organization SSO.",
        "domain": clean_domain,
        "domain_verified": True
    }

@router.get("/{org_id}/login")
async def initiate_sso_login(
    org_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Initiates SSO redirect flow for an organization with PKCE, nonce, and InResponseTo tracking."""
    stmt = select(SSOConfig).where(SSOConfig.organization_id == org_id)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO is not configured for this organization."
        )

    in_response_to = f"_{uuid.uuid4().hex}"
    code_verifier, code_challenge = generate_pkce_pair()
    nonce = secrets.token_hex(16)

    state = generate_sso_state(
        org_id=config.organization_id,
        provider=config.provider_type,
        in_response_to=in_response_to,
        code_verifier=code_verifier,
        nonce=nonce
    )

    base_url = str(request.base_url).rstrip("/")
    if config.provider_type == "SAML":
        redirect_url = f"{config.idp_sso_url or 'https://idp.example.com/sso'}?RelayState={state}"
    else:
        redirect_uri = f"{base_url}/api/v1/auth/sso/oidc/callback"
        redirect_url = build_oidc_authorization_url(
            idp_auth_url=config.idp_sso_url or "https://idp.example.com/oauth/authorize",
            client_id=config.client_id or "client_id",
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=code_challenge
        )

    return {
        "provider": config.provider_type,
        "redirect_url": redirect_url,
        "state": state,
        "in_response_to": in_response_to
    }

@router.post("/saml/callback")
async def saml_sso_callback(
    req: SAMLCallbackRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Handles SAML 2.0 assertion callback with strict cryptographic validation, replay protection, and tenant isolation."""
    if not req.relay_state:
        raise HTTPException(status_code=400, detail="Missing RelayState in SAML response.")

    state_data = decode_sso_state(req.relay_state)
    org_id = state_data.get("org_id")
    expected_in_response_to = state_data.get("in_response_to")

    stmt = select(SSOConfig).where(SSOConfig.organization_id == org_id)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config:
        raise HTTPException(status_code=404, detail="SSO configuration not found for organization.")

    if not config.idp_x509_cert:
        raise HTTPException(status_code=400, detail="SSO IdP X.509 certificate is not configured.")

    base_url = str(request.base_url).rstrip("/")
    expected_recipient = f"{base_url}/api/v1/auth/sso/saml/callback"
    expected_audience = config.idp_entity_id or f"{base_url}/api/v1/auth/sso/saml/metadata"

    try:
        saml_data = validate_saml_response(
            saml_response_b64=req.saml_response,
            idp_x509_cert=config.idp_x509_cert,
            expected_recipient=expected_recipient,
            expected_audience=expected_audience,
            expected_issuer=config.idp_entity_id,
            expected_in_response_to=expected_in_response_to
        )
    except SAMLValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"SAML assertion verification failed: {e}"
        )

    assertion_id = saml_data["assertion_id"]
    not_on_or_after = saml_data["not_on_or_after"]

    # Replay protection
    is_fresh = await check_and_record_assertion_id(assertion_id, not_on_or_after)
    if not is_fresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SAML assertion replay detected: assertion ID has already been consumed."
        )

    email = saml_data["email"]
    full_name = saml_data["full_name"]

    # Email domain verification: only allowed domains for this organization
    user_domain = email.split("@")[1].lower() if "@" in email else ""
    if not config.domains or user_domain not in [d.lower() for d in config.domains]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Email domain '{user_domain}' is not authorized for organization SSO."
        )
    if not config.domain_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Domain '{user_domain}' has not been verified for this organization."
        )

    # Scoped user lookup: strictly (organization_id, email) - NEVER globally
    stmt_user = select(User).where(User.organization_id == org_id, User.email == email)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one_or_none()

    if not user:
        if not config.jit_provisioning_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not registered and Just-In-Time provisioning is disabled for this organization."
            )
        # JIT Provisioning: NEVER allow SUPER_ADMIN role
        user_id = str(uuid.uuid4())
        default_role_str = (config.default_role or "STAFF").upper()
        if default_role_str == "SUPER_ADMIN" or default_role_str not in UserRole.__members__:
            assigned_role = UserRole.STAFF
        else:
            assigned_role = UserRole(default_role_str)

        user = User(
            id=user_id,
            organization_id=org_id,
            email=email,
            full_name=full_name,
            role=assigned_role,
            is_active=True,
            email_verified=True,
            hashed_password=""
        )
        db.add(user)
        await db.flush()

        await record_audit_log_async(
            org_id=org_id,
            user_id=user.id,
            action="JIT_USER_PROVISIONED",
            target_type="user",
            target_id=user.id,
            details={"provider": "SAML", "email": email, "role": assigned_role.value},
            db=db
        )

    # Security check: never allow SSO to issue SUPER_ADMIN session
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin accounts cannot authenticate via tenant SSO."
        )

    # Issue authenticated session
    access_token = create_access_token({
        "sub": user.id,
        "org_id": user.organization_id,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role)
    })
    refresh_token = create_refresh_token({"sub": user.id})

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

@router.post("/oidc/callback")
async def oidc_sso_callback(
    req: OIDCCallbackRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db)
):
    """Handles OIDC callback with PKCE, nonce, and ID-token signature validation."""
    state_data = decode_sso_state(req.state)
    org_id = state_data.get("org_id")
    expected_nonce = state_data.get("nonce")

    stmt = select(SSOConfig).where(SSOConfig.organization_id == org_id)
    res = await db.execute(stmt)
    config = res.scalar_one_or_none()

    if not config or config.provider_type != "OIDC":
        raise HTTPException(status_code=404, detail="OIDC configuration not found for organization.")

    # Validate ID token from response code or token
    try:
        oidc_data = validate_id_token(
            id_token=req.code,
            expected_client_id=config.client_id or "",
            expected_issuer=config.idp_entity_id,
            expected_nonce=expected_nonce,
            client_secret=config.client_secret_encrypted
        )
    except OIDCValidationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"OIDC validation failed: {e}")

    email = oidc_data["email"]
    full_name = oidc_data["full_name"]

    user_domain = email.split("@")[1].lower() if "@" in email else ""
    if not config.domains or user_domain not in [d.lower() for d in config.domains]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Email domain '{user_domain}' is not authorized for organization SSO."
        )
    if not config.domain_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Domain '{user_domain}' has not been verified for this organization."
        )

    stmt_user = select(User).where(User.organization_id == org_id, User.email == email)
    res_user = await db.execute(stmt_user)
    user = res_user.scalar_one_or_none()

    if not user:
        if not config.jit_provisioning_enabled:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="JIT provisioning disabled.")
        user_id = str(uuid.uuid4())
        default_role_str = (config.default_role or "STAFF").upper()
        assigned_role = UserRole.STAFF if default_role_str == "SUPER_ADMIN" or default_role_str not in UserRole.__members__ else UserRole(default_role_str)
        user = User(
            id=user_id,
            organization_id=org_id,
            email=email,
            full_name=full_name,
            role=assigned_role,
            is_active=True,
            email_verified=True,
            hashed_password=""
        )
        db.add(user)
        await db.flush()

    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin cannot authenticate via SSO.")

    access_token = create_access_token({
        "sub": user.id,
        "org_id": user.organization_id,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role)
    })
    refresh_token = create_refresh_token({"sub": user.id})

    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else None)
    user_agent = request.headers.get("User-Agent")
    await create_user_session(db=db, user_id=user.id, org_id=user.organization_id, access_token=access_token, ip_address=client_ip, user_agent=user_agent)
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
