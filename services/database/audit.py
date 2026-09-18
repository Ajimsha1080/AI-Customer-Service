import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.models import AuditLog

logger = logging.getLogger("hospitality_agent_cloud.audit")

async def record_audit_log_async(
    org_id: str,
    action: str,
    target_type: str,
    target_id: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None
) -> Optional[AuditLog]:
    """Records an immutable audit log entry for tenant boundary operations."""
    log_entry = AuditLog(
        organization_id=org_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details_json=details or {}
    )
    logger.info(f"AUDIT_LOG: org={org_id} user={user_id} action={action} target={target_type}:{target_id}")
    if db:
        db.add(log_entry)
        try:
            await db.flush()
        except Exception as e:
            logger.error(f"Failed to persist AuditLog to database: {e}")
    return log_entry
