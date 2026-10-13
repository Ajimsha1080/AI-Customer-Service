import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from urllib.parse import urlparse
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from services.database.session import set_tenant_context
from services.database.models import Subscription, Organization, ProcessedWebhookEvent
from services.billing.metering import SaaSMeteringService

logger = logging.getLogger("hospitality_agent_cloud.stripe")
metering_service = SaaSMeteringService()

PLAN_PRICE_MAP = {
    "STARTER": settings.STRIPE_PRICE_STARTER,
    "PROFESSIONAL": settings.STRIPE_PRICE_PROFESSIONAL,
    "BUSINESS": settings.STRIPE_PRICE_BUSINESS,
    "ENTERPRISE": settings.STRIPE_PRICE_ENTERPRISE,
}

PRICE_PLAN_REVERSE_MAP = {
    settings.STRIPE_PRICE_STARTER: "STARTER",
    settings.STRIPE_PRICE_PROFESSIONAL: "PROFESSIONAL",
    settings.STRIPE_PRICE_BUSINESS: "BUSINESS",
    settings.STRIPE_PRICE_ENTERPRISE: "ENTERPRISE",
}


def validate_redirect_url(url_str: str) -> None:
    """Validates that redirect URLs are well-formed and match allowed CORS origins."""
    if not url_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Redirect URL must not be empty."
        )
    parsed = urlparse(url_str)
    if not parsed.scheme or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redirect URL: missing scheme or hostname."
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed_origins = set(settings.CORS_ORIGINS)
    if origin not in allowed_origins:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Redirect URL origin '{origin}' is not authorized. Must match allowed tenant origins."
        )


class StripeBillingService:
    """Stripe Subscription Billing & Webhook Synchronization Service with Strict Verification."""

    def __init__(self):
        self.secret_key = settings.STRIPE_SECRET_KEY
        self.webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    async def create_checkout_session_async(
        self,
        organization_id: str,
        plan_name: str,
        success_url: str,
        cancel_url: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Creates a Stripe Checkout Session for subscription upgrade. Fails with 502 on Stripe error."""
        normalized_plan = plan_name.upper()
        if normalized_plan not in PLAN_PRICE_MAP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid subscription plan: {plan_name}. Valid plans: STARTER, PROFESSIONAL, BUSINESS, ENTERPRISE."
            )

        validate_redirect_url(success_url)
        validate_redirect_url(cancel_url)

        # Check existing subscription
        stmt = select(Subscription).where(Subscription.organization_id == organization_id)
        res = await db.execute(stmt)
        sub = res.scalar_one_or_none()
        customer_id = sub.stripe_customer_id if sub else None

        try:
            import stripe
            stripe.api_key = self.secret_key

            session_params = {
                "payment_method_types": ["card"],
                "mode": "subscription",
                "line_items": [{
                    "price": PLAN_PRICE_MAP[normalized_plan],
                    "quantity": 1,
                }],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": organization_id,
                "metadata": {
                    "organization_id": organization_id,
                    "target_plan": normalized_plan,
                    "price_id": PLAN_PRICE_MAP[normalized_plan],
                }
            }
            if customer_id:
                session_params["customer"] = customer_id

            session = stripe.checkout.Session.create(**session_params)
            return {
                "checkout_url": session.url,
                "session_id": session.id,
                "organization_id": organization_id,
                "plan_name": normalized_plan,
                "mode": "REAL_STRIPE"
            }
        except Exception as e:
            logger.error(f"Stripe Checkout creation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe payment gateway communication failure: {str(e)}"
            )

    async def create_customer_portal_session_async(
        self,
        organization_id: str,
        return_url: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Creates a Stripe Billing Customer Portal session."""
        validate_redirect_url(return_url)

        stmt = select(Subscription).where(Subscription.organization_id == organization_id)
        res = await db.execute(stmt)
        sub = res.scalar_one_or_none()

        if not sub or not sub.stripe_customer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No Stripe customer found for this organization. Upgrade via checkout first."
            )

        try:
            import stripe
            stripe.api_key = self.secret_key
            portal_session = stripe.billing_portal.Session.create(
                customer=sub.stripe_customer_id,
                return_url=return_url
            )
            return {"portal_url": portal_session.url}
        except Exception as e:
            logger.error(f"Stripe Customer Portal creation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Stripe customer portal communication failure: {str(e)}"
            )

    async def handle_webhook_event_async(
        self,
        payload_bytes: bytes,
        signature_header: str,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Strictly verifies Stripe webhook signature, prevents replay via idempotency, and derives plan from verified price ID."""
        if not signature_header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing Stripe-Signature header. Unsigned webhooks are rejected."
            )

        if not self.webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stripe webhook secret is not configured on the server."
            )

        try:
            import stripe
            stripe.api_key = self.secret_key
            constructed = stripe.Webhook.construct_event(
                payload_bytes, signature_header, self.webhook_secret
            )
            event = constructed.to_dict() if hasattr(constructed, "to_dict") else dict(constructed)
        except Exception as e:
            logger.warning(f"Stripe signature verification failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Stripe webhook signature: {str(e)}"
            )

        event_id = event.get("id")
        event_type = event.get("type", "unknown")
        event_data = event.get("data", {}).get("object", {})

        # 0.1 Idempotency Check
        if event_id:
            stmt = select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
            res = await db.execute(stmt)
            if res.scalar_one_or_none():
                logger.info(f"Stripe webhook event {event_id} already processed. Skipping duplicate.")
                return {"status": "duplicate", "event_id": event_id, "message": "Event already processed"}

        logger.info(f"Processing verified Stripe Webhook Event: {event_type} ({event_id})")

        if event_type == "checkout.session.completed":
            org_id = event_data.get("client_reference_id") or event_data.get("metadata", {}).get("organization_id")
            if org_id:
                await set_tenant_context(db, org_id)
            cust_id = event_data.get("customer")
            sub_id = event_data.get("subscription")

            # Derive plan strictly from verified price ID (no default "BUSINESS")
            price_id = None
            lines = event_data.get("lines", {}).get("data", [])
            if lines:
                price_id = lines[0].get("price", {}).get("id") or lines[0].get("plan", {}).get("id")
            if not price_id:
                line_items = event_data.get("line_items", {}).get("data", [])
                if line_items:
                    price_id = line_items[0].get("price", {}).get("id")
            if not price_id:
                price_id = event_data.get("metadata", {}).get("price_id")

            target_plan = None
            if price_id and price_id in PRICE_PLAN_REVERSE_MAP:
                target_plan = PRICE_PLAN_REVERSE_MAP[price_id]
            elif event_data.get("metadata", {}).get("target_plan"):
                candidate = event_data.get("metadata", {}).get("target_plan").upper()
                if candidate in PLAN_PRICE_MAP:
                    target_plan = candidate

            if not target_plan:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot derive valid plan from verified price ID or metadata. Default upgrade rejected."
                )

            if org_id:
                await metering_service.update_subscription_plan_async(org_id, target_plan, db=db)

                # Persist Stripe customer & subscription IDs
                stmt = select(Subscription).where(Subscription.organization_id == org_id)
                res = await db.execute(stmt)
                db_sub = res.scalar_one_or_none()
                if db_sub:
                    if cust_id:
                        db_sub.stripe_customer_id = cust_id
                    if sub_id:
                        db_sub.stripe_subscription_id = sub_id
                    db_sub.subscription_status = "active"
                    db_sub.dunning_attempt_count = 0
                    db_sub.dunning_last_failed_at = None
                    db_sub.dunning_grace_period_until = None

        elif event_type in ("invoice.paid", "customer.subscription.updated"):
            cust_id = event_data.get("customer")
            sub_id = event_data.get("id") or event_data.get("subscription")
            sub_status = event_data.get("status", "active")

            if cust_id or sub_id:
                stmt = select(Subscription).where(
                    (Subscription.stripe_customer_id == cust_id) | (Subscription.stripe_subscription_id == sub_id)
                )
                res = await db.execute(stmt)
                db_sub = res.scalar_one_or_none()
                if db_sub:
                    await set_tenant_context(db, db_sub.organization_id)
                    db_sub.subscription_status = sub_status
                    if sub_status == "active":
                        db_sub.dunning_attempt_count = 0
                        db_sub.dunning_last_failed_at = None
                        db_sub.dunning_grace_period_until = None

        elif event_type in ("customer.subscription.deleted", "invoice.payment_failed"):
            cust_id = event_data.get("customer")
            sub_id = event_data.get("id") or event_data.get("subscription")

            if cust_id or sub_id:
                stmt = select(Subscription).where(
                    (Subscription.stripe_customer_id == cust_id) | (Subscription.stripe_subscription_id == sub_id)
                )
                res = await db.execute(stmt)
                db_sub = res.scalar_one_or_none()
                if db_sub:
                    if event_type == "invoice.payment_failed":
                        db_sub.subscription_status = "past_due"
                        db_sub.dunning_attempt_count = (db_sub.dunning_attempt_count or 0) + 1
                        now = datetime.now(timezone.utc)
                        db_sub.dunning_last_failed_at = now
                        db_sub.dunning_grace_period_until = now + timedelta(days=7)
                    elif event_type == "customer.subscription.deleted":
                        db_sub.subscription_status = "canceled"
                        await metering_service.update_subscription_plan_async(db_sub.organization_id, "FREE", db=db)

        # Record processed event for idempotency
        if event_id:
            processed_record = ProcessedWebhookEvent(
                id=event_id,
                event_id=event_id,
                event_type=event_type,
                processed_at=datetime.now(timezone.utc)
            )
            db.add(processed_record)
        await db.commit()

        return {"status": "success", "event": event_type, "event_id": event_id}
