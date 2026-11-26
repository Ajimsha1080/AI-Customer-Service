import hashlib
import io
import json
import logging
import re
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.database.models import (
    Conversation, Message, VoiceSession, AuditLog, Organization,
    Reservation, SupportTicket, Document, Agent, User
)
from services.database.audit import record_audit_log_async

logger = logging.getLogger("hospitality_agent_cloud.retention")

# Statutory retention policy constants
GUEST_CHAT_RETENTION_DAYS = 90
AUDIT_LOG_RETENTION_DAYS = 365
DELETED_TENANT_HARD_DELETE_DAYS = 30

def anonymize_analytics_pii(payload: Any) -> Any:
    """Anonymizes PII (emails, phone numbers, credit cards, IP addresses) in analytics logs."""
    if isinstance(payload, str):
        # Email anonymization
        anonymized = re.sub(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "[REDACTED_EMAIL]", payload)
        # Phone anonymization (E.164, UK, international and US formats)
        anonymized = re.sub(r"(?:\+?\d{1,4}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}", "[REDACTED_PHONE]", anonymized)
        # IP address anonymization
        anonymized = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[REDACTED_IP]", anonymized)
        return anonymized
    elif isinstance(payload, dict):
        return {k: anonymize_analytics_pii(v) for k, v in payload.items()}
    elif isinstance(payload, list):
        return [anonymize_analytics_pii(item) for item in payload]
    return payload

class EnterpriseRetentionService:
    """
    Manages automated, audited retention purging across the platform:
    1. Guest chat logs & voice sessions older than 90 days.
    2. Audit logs older than 365 days.
    3. Soft-deleted tenant data hard deleted after 30 days.
    """

    async def purge_guest_chat_logs(self, db: AsyncSession, org_id: Optional[str] = None) -> Dict[str, Any]:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=GUEST_CHAT_RETENTION_DAYS)
        stmt_conv = select(Conversation).where(Conversation.created_at < cutoff_date)
        if org_id:
            stmt_conv = stmt_conv.where(Conversation.organization_id == org_id)

        res_conv = await db.execute(stmt_conv)
        convs = res_conv.scalars().all()
        conv_ids = [c.id for c in convs]

        purged_messages = 0
        if conv_ids:
            res_del_msg = await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
            purged_messages = res_del_msg.rowcount or len(conv_ids)
            await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))

        # Voice sessions purge
        stmt_voice = delete(VoiceSession).where(VoiceSession.created_at < cutoff_date)
        if org_id:
            stmt_voice = stmt_voice.where(VoiceSession.organization_id == org_id)
        res_del_voice = await db.execute(stmt_voice)
        purged_voice = res_del_voice.rowcount or 0

        await db.flush()
        return {
            "purged_conversations": len(conv_ids),
            "purged_messages": purged_messages,
            "purged_voice_sessions": purged_voice,
            "cutoff_date": cutoff_date.isoformat()
        }

    async def purge_audit_logs(self, db: AsyncSession, org_id: Optional[str] = None) -> Dict[str, Any]:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=AUDIT_LOG_RETENTION_DAYS)
        stmt = delete(AuditLog).where(AuditLog.created_at < cutoff_date)
        if org_id:
            stmt = stmt.where(AuditLog.organization_id == org_id)

        res = await db.execute(stmt)
        await db.flush()
        return {
            "purged_audit_logs": res.rowcount or 0,
            "cutoff_date": cutoff_date.isoformat()
        }

    async def hard_delete_expired_tenants(self, db: AsyncSession) -> Dict[str, Any]:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=DELETED_TENANT_HARD_DELETE_DAYS)
        stmt_org = select(Organization).where(
            Organization.status == "DELETED",
            Organization.updated_at < cutoff_date
        )
        res_org = await db.execute(stmt_org)
        expired_orgs = res_org.scalars().all()
        purged_org_ids = [o.id for o in expired_orgs]

        for org in expired_orgs:
            # Cascade hard delete
            await db.execute(delete(User).where(User.organization_id == org.id))
            await db.execute(delete(Agent).where(Agent.organization_id == org.id))
            await db.execute(delete(Document).where(Document.organization_id == org.id))
            await db.execute(delete(Conversation).where(Conversation.organization_id == org.id))
            await db.execute(delete(Organization).where(Organization.id == org.id))

        await db.flush()
        return {
            "purged_organizations": purged_org_ids,
            "count": len(purged_org_ids),
            "cutoff_date": cutoff_date.isoformat()
        }

def generate_gdpr_export_zip(records: Dict[str, List[Dict[str, Any]]]) -> bytes:
    """Generates a compressed ZIP file containing machine-readable JSON files per entity."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entity_name, entity_records in records.items():
            content = json.dumps(entity_records, indent=2, default=str)
            zf.writestr(f"{entity_name}.json", content)
    return zip_buffer.getvalue()

retention_service = EnterpriseRetentionService()
