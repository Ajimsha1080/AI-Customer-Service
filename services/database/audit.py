import json
import logging
import hashlib
from typing import Optional, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.models import AuditLog

logger = logging.getLogger("hospitality_agent_cloud.audit")

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"

def compute_entry_hash(
    prev_hash: str,
    org_id: str,
    user_id: Optional[str],
    action: str,
    target_type: str,
    target_id: str,
    details: Dict[str, Any]
) -> str:
    """Computes tamper-evident SHA-256 hash across canonical representation of audit entry."""
    details_str = json.dumps(details or {}, sort_keys=True)
    canonical = f"{prev_hash}|{org_id}|{user_id or ''}|{action}|{target_type}|{target_id}|{details_str}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

async def record_audit_log_async(
    org_id: str,
    action: str,
    target_type: str,
    target_id: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    db: Optional[AsyncSession] = None
) -> Optional[AuditLog]:
    """Records an immutable, hash-chained audit log entry guaranteeing tamper evidence."""
    prev_h = GENESIS_HASH
    details_dict = details or {}

    if db:
        try:
            # Query the latest audit entry in the tenant chain
            stmt = (
                select(AuditLog)
                .where(AuditLog.organization_id == org_id)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(1)
            )
            res = await db.execute(stmt)
            latest = res.scalar_one_or_none()
            if latest and latest.hash:
                prev_h = latest.hash
        except Exception as e:
            logger.warning(f"Could not retrieve previous audit hash, defaulting to genesis: {e}")

    curr_hash = compute_entry_hash(
        prev_hash=prev_h,
        org_id=org_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details_dict
    )

    log_entry = AuditLog(
        organization_id=org_id,
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details_json=details_dict,
        prev_hash=prev_h,
        hash=curr_hash
    )
    logger.info(f"AUDIT_CHAIN [hash={curr_hash[:12]} prev={prev_h[:12]}]: org={org_id} user={user_id} action={action}")
    if db:
        db.add(log_entry)
        try:
            await db.flush()
        except Exception as e:
            logger.error(f"Failed to persist AuditLog to database: {e}")
    return log_entry

async def verify_audit_log_chain(org_id: str, db: AsyncSession) -> Tuple[bool, int, Optional[str]]:
    """Cryptographically verifies the integrity of the append-only audit log chain for an organization.
    Returns (is_valid, verified_count, error_reason).
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.organization_id == org_id)
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
    )
    res = await db.execute(stmt)
    entries = res.scalars().all()

    if not entries:
        return True, 0, None

    expected_prev = GENESIS_HASH
    for idx, entry in enumerate(entries):
        # 1. Verify prev_hash matches prior entry's hash
        if idx == 0:
            # First entry in chain
            if entry.prev_hash != GENESIS_HASH and entry.prev_hash is not None:
                return False, idx, f"Genesis entry has invalid prev_hash: {entry.prev_hash}"
        else:
            if entry.prev_hash != expected_prev:
                return False, idx, f"Broken chain link at index {idx}: expected prev {expected_prev}, got {entry.prev_hash}"

        # 2. Recompute hash from entry attributes
        recomputed = compute_entry_hash(
            prev_hash=entry.prev_hash or GENESIS_HASH,
            org_id=entry.organization_id,
            user_id=entry.user_id,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            details=entry.details_json or {}
        )
        if entry.hash != recomputed:
            return False, idx, f"Tampered entry detected at index {idx}: stored {entry.hash}, recomputed {recomputed}"

        expected_prev = entry.hash

    return True, len(entries), None
