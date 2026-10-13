import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.models import Subscription, User, Invitation, Property, Agent, Document

logger = logging.getLogger("hospitality_agent_cloud.billing.entitlements")

PLAN_ENTITLEMENTS: Dict[str, Dict[str, Any]] = {
    "FREE": {
        "monthly_price": 0.0,
        "max_seats": 1,
        "max_agents": 1,
        "max_properties": 1,
        "max_conversations": 100,
        "max_voice_minutes": 0,
        "max_documents": 5,
        "features": {
            "voice_enabled": False,
            "custom_roles": False,
            "sso_saml": False,
            "byok_encryption": False,
            "siem_export": False,
            "scim_provisioning": False
        }
    },
    "STARTER": {
        "monthly_price": 49.0,
        "max_seats": 2,
        "max_agents": 2,
        "max_properties": 1,
        "max_conversations": 1000,
        "max_voice_minutes": 0,
        "max_documents": 20,
        "features": {
            "voice_enabled": False,
            "custom_roles": False,
            "sso_saml": False,
            "byok_encryption": False,
            "siem_export": False,
            "scim_provisioning": False
        }
    },
    "PROFESSIONAL": {
        "monthly_price": 199.0,
        "max_seats": 5,
        "max_agents": 5,
        "max_properties": 2,
        "max_conversations": 10000,
        "max_voice_minutes": 300,
        "max_documents": 100,
        "features": {
            "voice_enabled": True,
            "custom_roles": True,
            "sso_saml": False,
            "byok_encryption": False,
            "siem_export": False,
            "scim_provisioning": False
        }
    },
    "BUSINESS": {
        "monthly_price": 499.0,
        "max_seats": 20,
        "max_agents": 15,
        "max_properties": 5,
        "max_conversations": 50000,
        "max_voice_minutes": 1500,
        "max_documents": 500,
        "features": {
            "voice_enabled": True,
            "custom_roles": True,
            "sso_saml": True,
            "byok_encryption": False,
            "siem_export": True,
            "scim_provisioning": True
        }
    },
    "ENTERPRISE": {
        "monthly_price": 1999.0,
        "max_seats": 9999,
        "max_agents": 999,
        "max_properties": 999,
        "max_conversations": 9999999,
        "max_voice_minutes": 10000,
        "max_documents": 10000,
        "features": {
            "voice_enabled": True,
            "custom_roles": True,
            "sso_saml": True,
            "byok_encryption": True,
            "siem_export": True,
            "scim_provisioning": True
        }
    }
}

class EntitlementsService:
    """
    Unified Single Source of Truth for Tenant Entitlements, Seat Management,
    Dunning Grace Periods, and Spend Alerts.
    """
    async def get_tenant_plan_details(self, org_id: str, db: AsyncSession) -> Dict[str, Any]:
        stmt = select(Subscription).where(Subscription.organization_id == org_id)
        res = await db.execute(stmt)
        sub = res.scalar_one_or_none()
        plan_name = (sub.plan_name if sub else "FREE").upper()
        if plan_name not in PLAN_ENTITLEMENTS:
            plan_name = "FREE"
        entitlements = PLAN_ENTITLEMENTS[plan_name]

        return {
            "organization_id": org_id,
            "plan_name": plan_name,
            "status": sub.status if sub else "ACTIVE",
            "dunning_attempt_count": sub.dunning_attempt_count if sub else 0,
            "dunning_grace_period_until": sub.dunning_grace_period_until if sub else None,
            "limits": entitlements,
            "features": entitlements["features"]
        }

    async def can_access_feature(self, org_id: str, feature_key: str, db: AsyncSession) -> bool:
        details = await self.get_tenant_plan_details(org_id, db)
        return bool(details["features"].get(feature_key, False))

    async def check_seat_availability(self, org_id: str, db: AsyncSession) -> Tuple[bool, int, int]:
        """
        Calculates active user seats + pending invites against plan limit.
        Returns: (has_available_seat, current_allocated_seats, max_seats)
        """
        details = await self.get_tenant_plan_details(org_id, db)
        max_seats = details["limits"]["max_seats"]

        # 1. Count active users
        stmt_users = select(func.count(User.id)).where(User.organization_id == org_id, User.is_active == True)
        res_users = await db.execute(stmt_users)
        active_users = res_users.scalar() or 0

        # 2. Count pending invitations
        now = datetime.now(timezone.utc)
        stmt_inv = select(func.count(Invitation.id)).where(
            Invitation.organization_id == org_id,
            Invitation.accepted_at == None,
            Invitation.expires_at > now
        )
        res_inv = await db.execute(stmt_inv)
        pending_invites = res_inv.scalar() or 0

        allocated = active_users + pending_invites
        has_seat = allocated < max_seats
        return has_seat, allocated, max_seats

    def calculate_spend_alert_level(self, current_usage: int, limit: int) -> Optional[str]:
        """Returns proactive alert tier (80%, 100%, 120% or None)."""
        if limit <= 0:
            return None
        pct = (current_usage / limit) * 100
        if pct >= 120:
            return "CRITICAL_120_PERCENT_EXCEEDED"
        elif pct >= 100:
            return "WARNING_100_PERCENT_REACHED"
        elif pct >= 80:
            return "NOTICE_80_PERCENT_APPROACHING"
        return None

    def evaluate_dunning_status(
        self,
        subscription_status: str,
        dunning_grace_period_until: Optional[datetime]
    ) -> Dict[str, Any]:
        """
        Evaluates dunning lifecycle:
        - ACTIVE -> normal
        - IN_GRACE_PERIOD (payment failed, within 7 days) -> SOFT_DEGRADE (read-only for management, guest AI active)
        - GRACE_PERIOD_EXPIRED (> 7 days) -> HARD_SUSPEND
        """
        if subscription_status == "active":
            return {"status": "HEALTHY", "access_mode": "FULL_ACCESS"}

        now = datetime.now(timezone.utc)
        if dunning_grace_period_until:
            grace_exp = dunning_grace_period_until.replace(tzinfo=timezone.utc) if dunning_grace_period_until.tzinfo is None else dunning_grace_period_until
            if now <= grace_exp:
                return {
                    "status": "IN_DUNNING_GRACE_PERIOD",
                    "access_mode": "SOFT_DEGRADE_GUEST_ACTIVE",
                    "grace_period_ends": grace_exp.isoformat()
                }

        return {
            "status": "DUNNING_GRACE_PERIOD_EXPIRED",
            "access_mode": "HARD_SUSPEND",
            "action_required": "UPDATE_PAYMENT_METHOD"
        }

entitlements_service = EntitlementsService()
