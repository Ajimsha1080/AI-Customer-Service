import logging
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User
from services.security.email_service import email_service
from services.database.audit import record_audit_log_async

logger = logging.getLogger("hospitality_agent_cloud.webhooks.email")

router = APIRouter(prefix="/api/v1/webhooks/email", tags=["Email Webhooks"])

class BounceWebhookPayload(BaseModel):
    email: str
    bounce_type: Optional[str] = "hard_bounce"
    reason: Optional[str] = None

class ComplaintWebhookPayload(BaseModel):
    email: str
    complaint_type: Optional[str] = "spam"
    reason: Optional[str] = None

@router.post("/bounce")
async def handle_bounce_webhook(
    payload: BounceWebhookPayload,
    db: AsyncSession = Depends(get_db)
):
    """Processes bounce webhooks from SES/SendGrid; suppresses future dispatches and updates user state."""
    clean_email = payload.email.lower().strip()
    email_service.record_bounce(clean_email, reason=payload.bounce_type or "bounce")

    # Mark user email as unverified if registered
    stmt = select(User).where(User.email == clean_email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if user:
        user.email_verified = False
        await db.flush()
        await record_audit_log_async(
            org_id=user.organization_id,
            user_id=user.id,
            action="EMAIL_BOUNCED",
            target_type="user",
            target_id=user.id,
            details={"email": clean_email, "type": payload.bounce_type, "reason": payload.reason},
            db=db
        )

    return {"status": "recorded", "suppressed": True, "email": clean_email}

@router.post("/complaint")
async def handle_complaint_webhook(
    payload: ComplaintWebhookPayload,
    db: AsyncSession = Depends(get_db)
):
    """Processes spam complaint webhooks from SES/SendGrid; adds to suppression list."""
    clean_email = payload.email.lower().strip()
    email_service.record_complaint(clean_email)

    stmt = select(User).where(User.email == clean_email)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if user:
        user.email_verified = False
        await db.flush()
        await record_audit_log_async(
            org_id=user.organization_id,
            user_id=user.id,
            action="EMAIL_SPAM_COMPLAINT",
            target_type="user",
            target_id=user.id,
            details={"email": clean_email, "type": payload.complaint_type, "reason": payload.reason},
            db=db
        )

    return {"status": "recorded", "suppressed": True, "email": clean_email}
