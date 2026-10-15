from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.session import get_db
from services.database.models import User, Conversation, UsageEvent, UserRole
from apps.api.auth import get_current_user, verify_tenant_access
from services.billing.metering import SaaSMeteringService
from services.billing.stripe_service import StripeBillingService

router = APIRouter(tags=["SaaS Billing & Usage"])
metering_service = SaaSMeteringService()
stripe_service = StripeBillingService()

class PlanUpgradeRequest(BaseModel):
    plan_name: str

class CheckoutSessionRequest(BaseModel):
    plan_name: str
    success_url: Optional[str] = "http://localhost:3000/app/billing?session=success"
    cancel_url: Optional[str] = "http://localhost:3000/app/billing?session=cancel"

@router.get("/api/v1/billing/subscription")
async def get_subscription_status(
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    sub = await metering_service.get_or_create_subscription_async(org_id, db=db)
    summary = await metering_service.get_organization_usage_summary_async(org_id, db=db)
    return {
        "subscription": sub,
        "usage_summary": summary
    }

class CustomerPortalRequest(BaseModel):
    return_url: Optional[str] = "http://localhost:3000/app/billing"

@router.post("/api/v1/billing/subscription/upgrade")
async def upgrade_subscription_plan(
    req: PlanUpgradeRequest,
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Direct self-upgrade is forbidden for tenant administrators. Subscriptions must be upgraded via Stripe Checkout."
        )
    org_id = verify_tenant_access(current_user, organization_id)
    try:
        return await metering_service.update_subscription_plan_async(org_id, req.plan_name, db=db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/api/v1/billing/customer-portal")
async def create_customer_portal(
    req: CustomerPortalRequest,
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Generates a Stripe Customer Portal link for managing subscription and payment methods."""
    org_id = verify_tenant_access(current_user, organization_id)
    return await stripe_service.create_customer_portal_session_async(
        organization_id=org_id,
        return_url=req.return_url,
        db=db
    )

@router.post("/api/v1/billing/checkout-session")
async def create_stripe_checkout_session(
    req: CheckoutSessionRequest,
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Creates a Stripe Checkout Session for subscription upgrade."""
    org_id = verify_tenant_access(current_user, organization_id)
    return await stripe_service.create_checkout_session_async(
        organization_id=org_id,
        plan_name=req.plan_name,
        success_url=req.success_url,
        cancel_url=req.cancel_url,
        db=db
    )

@router.post("/api/v1/billing/webhook")
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db)
):
    """Stripe Webhook Listener (checkout.session.completed, invoice.paid, etc.). Rejects unsigned payloads."""
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stripe-Signature header is required. Unsigned webhooks are rejected."
        )
    payload_bytes = await request.body()
    result = await stripe_service.handle_webhook_event_async(
        payload_bytes=payload_bytes,
        signature_header=stripe_signature,
        db=db
    )
    return result

@router.get("/api/v1/usage")
async def get_usage(
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    return await metering_service.get_organization_usage_summary_async(org_id, db=db)

@router.get("/api/v1/analytics", tags=["Platform & Agent Analytics"])
async def get_analytics(
    organization_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    org_id = verify_tenant_access(current_user, organization_id)
    from datetime import datetime
    from services.database.models import Message, ConversationStatus

    conv_query = select(Conversation).where(Conversation.organization_id == org_id)
    usage_query = select(UsageEvent).where(UsageEvent.organization_id == org_id)

    if start_date:
        try:
            s_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            conv_query = conv_query.where(Conversation.created_at >= s_dt)
            usage_query = usage_query.where(UsageEvent.created_at >= s_dt)
        except Exception:
            pass
    if end_date:
        try:
            e_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            conv_query = conv_query.where(Conversation.created_at <= e_dt)
            usage_query = usage_query.where(UsageEvent.created_at <= e_dt)
        except Exception:
            pass

    conv_res = await db.execute(conv_query)
    conversations = conv_res.scalars().all()
    convs_count = len(conversations)

    usage_res = await db.execute(usage_query)
    usage_events = usage_res.scalars().all()
    events_count = len(usage_events)

    escalation_statuses = {
        ConversationStatus.HUMAN_REQUESTED,
        ConversationStatus.HUMAN_ACTIVE,
        ConversationStatus.HUMAN_STAFF_TAKEN_OVER,
    }
    escalated_count = sum(
        1 for c in conversations
        if bool(c.is_human_takeover) or (c.status in escalation_statuses)
    )
    resolved_count = sum(
        1 for c in conversations
        if c.status == ConversationStatus.RESOLVED and not c.is_human_takeover
    )

    ai_res_rate = f"{(resolved_count / convs_count * 100):.1f}%" if convs_count > 0 else "0.0%"
    human_esc_rate = f"{(escalated_count / convs_count * 100):.1f}%" if convs_count > 0 else "0.0%"

    total_cost = sum(float(ev.estimated_cost or 0.0) for ev in usage_events)

    channel_counts = {}
    for c in conversations:
        ch = c.channel or "web_widget"
        channel_counts[ch] = channel_counts.get(ch, 0) + 1

    top_channels = {
        ch: f"{(count / convs_count * 100):.1f}%"
        for ch, count in channel_counts.items()
    } if convs_count > 0 else {}

    conv_ids = [c.id for c in conversations]
    avg_latency = 0
    if conv_ids:
        msg_query = select(Message).where(Message.conversation_id.in_(conv_ids[:1000]))
        msg_res = await db.execute(msg_query)
        messages = msg_res.scalars().all()
        latencies = [
            m.metadata_json.get("latency_ms")
            for m in messages
            if m.metadata_json and isinstance(m.metadata_json.get("latency_ms"), (int, float))
        ]
        if latencies:
            avg_latency = int(sum(latencies) / len(latencies))

    return {
        "organization_id": org_id,
        "total_conversations": convs_count,
        "total_usage_events": events_count,
        "ai_resolution_rate": ai_res_rate,
        "human_escalation_rate": human_esc_rate,
        "average_response_time_ms": avg_latency,
        "total_cost_usd": round(total_cost, 4),
        "top_channels": top_channels
    }

@router.get("/api/v1/billing/entitlements")
async def get_organization_entitlements(
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Unified entitlements and seat quota status."""
    from services.billing.entitlements import entitlements_service
    org_id = verify_tenant_access(current_user, organization_id)
    plan_details = await entitlements_service.get_tenant_plan_details(org_id, db)
    has_seat, allocated_seats, max_seats = await entitlements_service.check_seat_availability(org_id, db)

    summary = await metering_service.get_organization_usage_summary_async(org_id, db=db)
    current_turns = summary.get("current_month_turns", 0)
    limit_turns = plan_details["limits"]["max_conversations"]
    alert_tier = entitlements_service.calculate_spend_alert_level(current_turns, limit_turns)

    return {
        "organization_id": org_id,
        "plan": plan_details["plan_name"],
        "features": plan_details["features"],
        "limits": plan_details["limits"],
        "seats": {
            "has_available_seat": has_seat,
            "allocated_seats": allocated_seats,
            "max_seats": max_seats
        },
        "spend_alert_tier": alert_tier
    }

@router.get("/api/v1/billing/dunning-status")
async def get_dunning_status(
    organization_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Evaluates dunning lifecycle: healthy, soft degrade (grace period), or hard suspend."""
    from services.billing.entitlements import entitlements_service
    org_id = verify_tenant_access(current_user, organization_id)
    sub = await metering_service.get_or_create_subscription_async(org_id, db=db)
    dunning_info = entitlements_service.evaluate_dunning_status(
        subscription_status=sub.get("subscription_status", "active"),
        dunning_grace_period_until=sub.get("dunning_grace_period_until")
    )
    return {
        "organization_id": org_id,
        "subscription_status": sub.get("subscription_status", "active"),
        "dunning": dunning_info,
        "portal_recovery_url": "/app/billing"
    }

