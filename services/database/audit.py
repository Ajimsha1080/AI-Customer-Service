import json
import logging
import hashlib
import hmac
from typing import Optional, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.database.models import AuditLog

logger = logging.getLogger("hospitality_agent_cloud.audit")

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"
ACTIVE_KEY_VERSION = "v1"

def _get_signing_keys() -> Dict[str, str]:
    """Retrieves HMAC signing keys supporting key rotation."""
    from apps.api.config import settings
    configured = getattr(settings, "AUDIT_SIGNING_KEYS", None)
    if isinstance(configured, dict):
        return configured
    if isinstance(configured, str) and configured.startswith("{"):
        try:
            return json.loads(configured)
        except Exception:
            pass
    secret = getattr(settings, "SECRET_KEY", "audit_hmac_secret_key_rotation_default")
    return {ACTIVE_KEY_VERSION: secret}

def compute_entry_hash(
    prev_hash: str,
    org_id: str,
    user_id: Optional[str],
    action: str,
    target_type: str,
    target_id: str,
    details: Dict[str, Any],
    key_version: Optional[str] = None
) -> str:
    """Computes tamper-evident HMAC-SHA256 signature across canonical representation of audit entry,
    incorporating prev_hash and all fields.
    """
    version = key_version or ACTIVE_KEY_VERSION
    keys = _get_signing_keys()
    key = keys.get(version, keys.get(ACTIVE_KEY_VERSION, "default_secret"))
    details_str = json.dumps(details or {}, sort_keys=True)
    canonical = f"{prev_hash}|{org_id}|{user_id or ''}|{action}|{target_type}|{target_id}|{details_str}"
    sig = hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{version}:{sig}"

def verify_entry_hash(
    stored_hash: str,
    prev_hash: str,
    org_id: str,
    user_id: Optional[str],
    action: str,
    target_type: str,
    target_id: str,
    details: Dict[str, Any]
) -> bool:
    """Verifies that stored hash matches canonical representation, supporting rotated HMAC keys and legacy SHA256."""
    if not stored_hash:
        return False

    keys = _get_signing_keys()
    details_str = json.dumps(details or {}, sort_keys=True)
    canonical = f"{prev_hash}|{org_id}|{user_id or ''}|{action}|{target_type}|{target_id}|{details_str}"

    if ":" in stored_hash:
        version, sig = stored_hash.split(":", 1)
        key = keys.get(version)
        if not key:
            logger.warning(f"Audit log key version '{version}' not found in active key rotation set.")
            return False
        expected_sig = hmac.new(key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    else:
        # Check against legacy raw SHA256
        legacy = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if hmac.compare_digest(stored_hash, legacy):
            return True
        # Check against default HMAC key
        def_key = keys.get(ACTIVE_KEY_VERSION, "")
        hmac_sig = hmac.new(def_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(stored_hash, hmac_sig)

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
    logger.info(f"AUDIT_CHAIN [hash={curr_hash[:16]} prev={prev_h[:16]}]: org={org_id} user={user_id} action={action}")
    if db:
        db.add(log_entry)
        try:
            await db.flush()
        except Exception as e:
            logger.error(f"Failed to persist AuditLog to database: {e}")
    return log_entry

async def verify_audit_log_chain(org_id: str, db: AsyncSession) -> Tuple[bool, int, Optional[str]]:
    """Cryptographically verifies the integrity of the append-only audit log chain for an organization.
    Alerts critically on broken links or tampered entries.
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
            if entry.prev_hash != GENESIS_HASH and entry.prev_hash is not None:
                err = f"Genesis entry has invalid prev_hash: {entry.prev_hash}"
                logger.critical(f"AUDIT_CHAIN_INTEGRITY_BREACH: [org={org_id}, index={idx}] {err}")
                return False, idx, err
        else:
            if entry.prev_hash != expected_prev:
                err = f"Broken chain link at index {idx}: expected prev {expected_prev}, got {entry.prev_hash}"
                logger.critical(f"AUDIT_CHAIN_INTEGRITY_BREACH: [org={org_id}, index={idx}] {err}")
                return False, idx, err

        # 2. Verify HMAC cryptographic signature across all fields
        is_entry_valid = verify_entry_hash(
            stored_hash=entry.hash,
            prev_hash=entry.prev_hash or GENESIS_HASH,
            org_id=entry.organization_id,
            user_id=entry.user_id,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            details=entry.details_json or {}
        )
        if not is_entry_valid:
            err = f"Tampered entry detected at index {idx}: signature mismatch for entry {entry.id}"
            logger.critical(f"AUDIT_CHAIN_INTEGRITY_BREACH: [org={org_id}, index={idx}, entry_id={entry.id}] {err}")
            return False, idx, err

        expected_prev = entry.hash

    return True, len(entries), None
