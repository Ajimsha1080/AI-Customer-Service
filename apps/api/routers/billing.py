from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, Conversation, UsageEvent
from apps.api.auth import get_current_user, verify_tenant_access
from services.billing.metering import SaaSMeteringService

router = APIRouter(tags=["SaaS Billing & Usage"])
metering_service = SaaSMeteringService()

class PlanUpgradeRequest(BaseModel):
    plan_name: str

@router.get("/api/v1/billing/subscription")
async def get_subscription_status(organization_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    sub = await metering_service.get_or_create_subscription_async(org_id, db=db)
    summary = await metering_service.get_organization_usage_summary_async(org_id, db=db)
    return {
        "subscription": sub,
        "usage_summary": summary
    }

@router.post("/api/v1/billing/subscription/upgrade")
async def upgrade_subscription_plan(req: PlanUpgradeRequest, organization_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    try:
        return await metering_service.update_subscription_plan_async(org_id, req.plan_name, db=db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/api/v1/usage")
async def get_usage(organization_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    return await metering_service.get_organization_usage_summary_async(org_id, db=db)

@router.get("/api/v1/analytics", tags=["Platform & Agent Analytics"])
async def get_analytics(organization_id: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    org_id = verify_tenant_access(current_user, organization_id)
    convs_count = (await db.execute(select(func.count(Conversation.id)).where(Conversation.organization_id == org_id))).scalar() or 0
    events_count = (await db.execute(select(func.count(UsageEvent.id)).where(UsageEvent.organization_id == org_id))).scalar() or 0
    
    return {
        "organization_id": org_id,
        "total_conversations": convs_count,
        "total_usage_events": events_count,
        "ai_resolution_rate": "94.5%",
        "human_escalation_rate": "5.5%",
        "average_response_time_ms": 340,
        "total_cost_usd": round(events_count * 0.002, 2),
        "top_channels": {"web_widget": "65%", "whatsapp": "25%", "voice": "10%"}
    }
