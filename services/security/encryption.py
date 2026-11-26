import os
import base64
import json
import secrets
import hashlib
import logging
from typing import Optional, Dict, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from apps.api.config import settings
from services.common.redis_service import get_redis_client_sync

logger = logging.getLogger("hospitality_agent_cloud.security.encryption")

class EnvelopeEncryptionService:
    """Enterprise KMS-backed Envelope Encryption (AES-256-GCM).
    Uses AWS KMS (or KEK fallback in dev/test) to generate and wrap ephemeral Data Encryption Keys (DEKs).
    Supports per-tenant Bring-Your-Own-Key (BYOK) KMS ARNs stored in Redis/DB and zero-downtime key rotation.
    
    In production, AWS KMS is strictly required and fails on startup/execution if missing.
    """
    def __init__(self, master_key_hex: Optional[str] = None):
        if master_key_hex and len(master_key_hex) == 64:
            self.root_kek = bytes.fromhex(master_key_hex)
        else:
            self.root_kek = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        
        self.tenant_byok_store: Dict[str, bytes] = {}
        self.tenant_byok_arn_store: Dict[str, str] = {}
        self._kms_client = None

    @property
    def kms_client(self):
        if self._kms_client is None:
            try:
                import boto3
                self._kms_client = boto3.client("kms", region_name=settings.KMS_REGION)
            except Exception as e:
                if settings.is_production:
                    raise RuntimeError(f"CRITICAL: Failed to initialize AWS KMS client in production: {e}")
                self._kms_client = None
        return self._kms_client

    def _redis(self):
        try:
            return get_redis_client_sync()
        except Exception:
            return None

    def register_tenant_byok_arn(self, org_id: str, kms_arn: str) -> None:
        """Configures a custom tenant-supplied AWS KMS ARN for Enterprise plan tenants."""
        if not kms_arn or not kms_arn.startswith("arn:aws:kms:"):
            raise ValueError("Tenant BYOK KMS Key must be a valid AWS KMS ARN (arn:aws:kms:...).")
        self.tenant_byok_arn_store[org_id] = kms_arn
        r = self._redis()
        if r:
            try:
                r.set(f"hac:byok_arn:{org_id}", kms_arn)
            except Exception as e:
                if settings.is_production:
                    raise RuntimeError(f"Failed to store BYOK KMS ARN in Redis: {e}")

    def register_tenant_byok(self, org_id: str, byok_key_hex: str) -> None:
        """Configures a custom tenant-supplied KEK (hex or ARN) for Enterprise plan tenants."""
        if byok_key_hex.startswith("arn:aws:kms:"):
            self.register_tenant_byok_arn(org_id, byok_key_hex)
            return
        if len(byok_key_hex) != 64:
            raise ValueError("Tenant BYOK key must be a 64-character hex string (256 bits) or KMS ARN.")
        key_bytes = bytes.fromhex(byok_key_hex)
        self.tenant_byok_store[org_id] = key_bytes
        r = self._redis()
        if r:
            try:
                r.set(f"hac:byok:{org_id}", byok_key_hex)
            except Exception as e:
                if settings.is_production:
                    raise RuntimeError(f"Failed to store BYOK key in Redis: {e}")

    def remove_tenant_byok(self, org_id: str) -> None:
        """Removes custom BYOK key, reverting back to platform master KEK / KMS primary key."""
        self.tenant_byok_store.pop(org_id, None)
        self.tenant_byok_arn_store.pop(org_id, None)
        r = self._redis()
        if r:
            try:
                r.delete(f"hac:byok:{org_id}")
                r.delete(f"hac:byok_arn:{org_id}")
            except Exception:
                pass

    def _get_tenant_byok_arn(self, org_id: Optional[str] = None) -> Optional[str]:
        if not org_id:
            return None
        r = self._redis()
        if r:
            try:
                val = r.get(f"hac:byok_arn:{org_id}")
                if val:
                    return val.decode("utf-8") if isinstance(val, bytes) else val
            except Exception:
                pass
        return self.tenant_byok_arn_store.get(org_id)

    def _get_kek(self, org_id: Optional[str] = None) -> bytes:
        if org_id:
            r = self._redis()
            if r:
                try:
                    val = r.get(f"hac:byok:{org_id}")
                    if val:
                        hex_str = val.decode("utf-8") if isinstance(val, bytes) else val
                        return bytes.fromhex(hex_str)
                except Exception:
                    pass
            if org_id in self.tenant_byok_store:
                return self.tenant_byok_store[org_id]
        return self.root_kek

    def encrypt(self, plaintext: str, org_id: Optional[str] = None, kms_arn: Optional[str] = None) -> str:
        """Encrypts plaintext using AWS KMS envelope encryption (ephemeral DEK wrapped by KMS KEK)."""
        if not plaintext:
            return ""

        # Determine target KMS ARN
        target_arn = kms_arn or self._get_tenant_byok_arn(org_id)
        if not target_arn and settings.KMS_PRIMARY_KEY_ID:
            target_arn = settings.KMS_PRIMARY_KEY_ID

        # If AWS KMS is configured or forced in production
        if settings.is_production or (target_arn and self.kms_client is not None):
            if not target_arn:
                raise RuntimeError("Production requires AWS KMS primary key ID or tenant BYOK ARN configured.")
            if self.kms_client is None:
                raise RuntimeError("AWS KMS client is unavailable for envelope encryption.")

            # 1. Ask AWS KMS to generate an ephemeral 256-bit DEK
            kms_resp = self.kms_client.generate_data_key(
                KeyId=target_arn,
                KeySpec="AES_256"
            )
            plaintext_dek = kms_resp["Plaintext"]
            ciphertext_blob = kms_resp["CiphertextBlob"]

            # 2. Encrypt plaintext locally with DEK using AES-256-GCM
            aesgcm_dek = AESGCM(plaintext_dek)
            iv_data = secrets.token_bytes(12)
            ciphertext_bytes = aesgcm_dek.encrypt(iv_data, plaintext.encode("utf-8"), None)

            # 3. Securely discard plaintext DEK from memory
            del plaintext_dek

            # 4. Serialize envelope: v2:aws_kms:<w_dek>:<iv_data>:<ciphertext_bytes>
            envelope = {
                "v": 2,
                "provider": "aws_kms",
                "w_dek": base64.b64encode(ciphertext_blob).decode("utf-8"),
                "iv_d": base64.b64encode(iv_data).decode("utf-8"),
                "ct": base64.b64encode(ciphertext_bytes).decode("utf-8"),
                "kms_arn": target_arn
            }
            return "env:" + base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")

        # Fallback to local AES-256-GCM envelope in development/testing
        kek = self._get_kek(org_id)
        dek = AESGCM.generate_key(bit_length=256)
        aesgcm_dek = AESGCM(dek)
        iv_data = secrets.token_bytes(12)
        ciphertext_bytes = aesgcm_dek.encrypt(iv_data, plaintext.encode("utf-8"), None)
        aesgcm_kek = AESGCM(kek)
        iv_kek = secrets.token_bytes(12)
        wrapped_dek = aesgcm_kek.encrypt(iv_kek, dek, None)

        envelope = {
            "v": 1,
            "provider": "local_aes",
            "w_dek": base64.b64encode(wrapped_dek).decode("utf-8"),
            "iv_k": base64.b64encode(iv_kek).decode("utf-8"),
            "iv_d": base64.b64encode(iv_data).decode("utf-8"),
            "ct": base64.b64encode(ciphertext_bytes).decode("utf-8")
        }
        return "env:" + base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")

    def decrypt(self, envelope_str: str, org_id: Optional[str] = None) -> str:
        """Unwraps ephemeral DEK using AWS KMS or local KEK and decrypts ciphertext."""
        if not envelope_str:
            return ""
        if not envelope_str.startswith("env:"):
            return envelope_str

        raw_json = base64.b64decode(envelope_str[4:]).decode("utf-8")
        envelope = json.loads(raw_json)

        provider = envelope.get("provider")
        version = envelope.get("v", 1)

        # Handle AWS KMS envelope (v2)
        if provider == "aws_kms" or version == 2:
            # Check tenant BYOK isolation: if org has a dedicated BYOK ARN, it must match envelope's kms_arn
            tenant_arn = self._get_tenant_byok_arn(org_id)
            if tenant_arn and envelope.get("kms_arn") and tenant_arn != envelope.get("kms_arn"):
                raise ValueError("Cross-tenant decryption rejected: BYOK KMS ARN mismatch.")

            if self.kms_client is None:
                raise RuntimeError("AWS KMS client is unavailable for envelope decryption.")

            wrapped_dek = base64.b64decode(envelope["w_dek"])
            iv_data = base64.b64decode(envelope["iv_d"])
            ciphertext_bytes = base64.b64decode(envelope["ct"])

            # Call AWS KMS Decrypt
            kms_resp = self.kms_client.decrypt(CiphertextBlob=wrapped_dek)
            plaintext_dek = kms_resp["Plaintext"]

            aesgcm_dek = AESGCM(plaintext_dek)
            plaintext_bytes = aesgcm_dek.decrypt(iv_data, ciphertext_bytes, None)
            del plaintext_dek
            return plaintext_bytes.decode("utf-8")

        # Handle local AES-256-GCM envelope (v1)
        kek = self._get_kek(org_id)
        wrapped_dek = base64.b64decode(envelope["w_dek"])
        iv_kek = base64.b64decode(envelope["iv_k"])
        iv_data = base64.b64decode(envelope["iv_d"])
        ciphertext_bytes = base64.b64decode(envelope["ct"])

        aesgcm_kek = AESGCM(kek)
        dek = aesgcm_kek.decrypt(iv_kek, wrapped_dek, None)
        aesgcm_dek = AESGCM(dek)
        plaintext_bytes = aesgcm_dek.decrypt(iv_data, ciphertext_bytes, None)
        return plaintext_bytes.decode("utf-8")

    def rotate_envelope(self, envelope_str: str, old_org_id: Optional[str] = None, new_org_id: Optional[str] = None) -> str:
        """Decrypts with current KEK/KMS and re-encrypts with new KEK/KMS (for key rotation or BYOK migration)."""
        decrypted = self.decrypt(envelope_str, org_id=old_org_id)
        return self.encrypt(decrypted, org_id=new_org_id)

encryption_service = EnvelopeEncryptionService()

def encrypt_value(plaintext: str, org_id: Optional[str] = None) -> str:
    """Convenience helper to encrypt a value with envelope encryption."""
    return encryption_service.encrypt(plaintext, org_id=org_id)

def decrypt_value(envelope_str: str, org_id: Optional[str] = None) -> str:
    """Convenience helper to decrypt an envelope encrypted value."""
    return encryption_service.decrypt(envelope_str, org_id=org_id)
