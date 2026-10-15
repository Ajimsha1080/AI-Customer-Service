import uuid
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, ApiKey, WebhookSubscription, WebhookDeliveryLog
from services.integrations.webhooks import dispatch_customer_webhook
from services.database.audit import record_audit_log_async
from apps.api.auth import get_current_user, require_permission
from services.resilience.tenant_limiter import enforce_tenant_fair_use_quota
from services.database.pagination import paginate_query

router = APIRouter(prefix="/api/v1/developer", tags=["Developer Platform: API Keys & Webhooks"], dependencies=[Depends(enforce_tenant_fair_use_quota)])

class CreateApiKeyRequest(BaseModel):
    name: str
    scopes: List[str] = ["reservations:read", "conversations:read"]
    rate_limit_per_minute: int = 60
    expires_in_days: Optional[int] = 90

class CreateWebhookRequest(BaseModel):
    endpoint_url: str
    events: List[str] = ["reservation.created", "conversation.message_received"]

@router.post("/api-keys")
async def create_api_key(
    req: CreateApiKeyRequest,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """Generates a scoped API key. The raw secret is returned ONLY ONCE."""
    raw_secret = secrets.token_urlsafe(32)
    key_prefix = f"hac_{raw_secret[:7]}"
    full_key = f"{key_prefix}_{raw_secret}"
    key_hash = hashlib.sha256(full_key.encode("utf-8")).hexdigest()

    expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days) if req.expires_in_days else None

    api_key_entry = ApiKey(
        id=f"key_{uuid.uuid4().hex[:12]}",
        organization_id=current_user.organization_id,
        name=req.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=req.scopes,
        rate_limit_per_minute=req.rate_limit_per_minute,
        expires_at=expires_at,
        is_active=True
    )
    db.add(api_key_entry)
    await db.commit()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="API_KEY_CREATED",
        target_type="api_key",
        target_id=api_key_entry.id,
        details={"name": req.name, "prefix": key_prefix, "scopes": req.scopes},
        db=db
    )

    return {
        "id": api_key_entry.id,
        "name": api_key_entry.name,
        "key_prefix": key_prefix,
        "api_key": full_key,  # One-time disclosure
        "scopes": req.scopes,
        "rate_limit_per_minute": req.rate_limit_per_minute,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "message": "Store this API key safely. It will not be shown again."
    }

@router.get("/api-keys")
async def list_api_keys(
    current_user: User = Depends(require_permission("org:read")),
    db: AsyncSession = Depends(get_db)
):
    """Lists active API keys for the current organization."""
    stmt = select(ApiKey).where(
        ApiKey.organization_id == current_user.organization_id,
        ApiKey.is_active == True
    )
    res = await db.execute(stmt)
    keys = res.scalars().all()
    return {
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "scopes": k.scopes,
                "rate_limit_per_minute": k.rate_limit_per_minute,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "created_at": k.created_at.isoformat() if k.created_at else None
            }
            for k in keys
        ]
    }

@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """Revokes an API key immediately."""
    stmt = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.organization_id == current_user.organization_id
    )
    res = await db.execute(stmt)
    k = res.scalar_one_or_none()
    if not k:
        raise HTTPException(status_code=404, detail="API key not found.")

    k.is_active = False
    await db.commit()

    await record_audit_log_async(
        org_id=current_user.organization_id,
        user_id=current_user.id,
        action="API_KEY_REVOKED",
        target_type="api_key",
        target_id=key_id,
        details={"name": k.name, "prefix": k.key_prefix},
        db=db
    )
    return {"status": "success", "revoked_key_id": key_id}

@router.post("/webhooks")
async def subscribe_webhook(
    req: CreateWebhookRequest,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """Registers customer webhook subscription with generated HMAC secret."""
    secret = secrets.token_hex(24)
    sub = WebhookSubscription(
        id=f"whsub_{uuid.uuid4().hex[:12]}",
        organization_id=current_user.organization_id,
        endpoint_url=req.endpoint_url,
        secret_encrypted=secret,
        events=req.events,
        is_active=True
    )
    db.add(sub)
    await db.commit()

    return {
        "id": sub.id,
        "endpoint_url": sub.endpoint_url,
        "secret": secret,
        "events": sub.events,
        "created_at": sub.created_at.isoformat() if sub.created_at else None
    }

@router.post("/webhooks/{sub_id}/test")
async def test_webhook_delivery(
    sub_id: str,
    current_user: User = Depends(require_permission("org:write")),
    db: AsyncSession = Depends(get_db)
):
    """Triggers an HMAC-signed test ping to customer webhook endpoint."""
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.id == sub_id,
        WebhookSubscription.organization_id == current_user.organization_id
    )
    res = await db.execute(stmt)
    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found.")

    test_payload = {
        "event_type": "webhook.test_ping",
        "ping_id": f"ping_{uuid.uuid4().hex[:8]}",
        "message": "Verification test delivery from Hospitality Agent Cloud"
    }
    delivery_log = await dispatch_customer_webhook(db, sub, "webhook.test_ping", test_payload)
    return {
        "delivery_id": delivery_log.id,
        "status": "DELIVERED",
        "status_code": delivery_log.status_code,
        "endpoint_url": sub.endpoint_url
    }
