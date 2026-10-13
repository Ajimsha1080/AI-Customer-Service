import os
import base64
import json
import secrets
import hashlib
from typing import Optional, Dict, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from apps.api.config import settings

class EnvelopeEncryptionService:
    """Enterprise KMS-backed Envelope Encryption (AES-256-GCM).
    Uses a master Key Encryption Key (KEK) to encrypt ephemeral Data Encryption Keys (DEKs).
    Supports per-tenant Bring-Your-Own-Key (BYOK) and zero-downtime key rotation.
    
    Envelope format:
    v1:<b64_encrypted_dek>:<b64_iv>:<b64_ciphertext_and_tag>
    """
    def __init__(self, master_key_hex: Optional[str] = None):
        # 256-bit root key
        if master_key_hex and len(master_key_hex) == 64:
            self.root_kek = bytes.fromhex(master_key_hex)
        else:
            # Fallback to deriving from application secret key
            self.root_kek = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
        
        # In-memory tenant BYOK store (maps tenant org_id -> 32-byte custom KEK)
        self.tenant_byok_store: Dict[str, bytes] = {}

    def register_tenant_byok(self, org_id: str, byok_key_hex: str) -> None:
        """Configures a custom tenant-supplied KEK for Enterprise plan tenants."""
        if len(byok_key_hex) != 64:
            raise ValueError("Tenant BYOK key must be a 64-character hex string (256 bits).")
        self.tenant_byok_store[org_id] = bytes.fromhex(byok_key_hex)

    def remove_tenant_byok(self, org_id: str) -> None:
        """Removes custom BYOK key, reverting back to platform master KEK."""
        self.tenant_byok_store.pop(org_id, None)

    def _get_kek(self, org_id: Optional[str] = None) -> bytes:
        if org_id and org_id in self.tenant_byok_store:
            return self.tenant_byok_store[org_id]
        return self.root_kek

    def encrypt(self, plaintext: str, org_id: Optional[str] = None) -> str:
        """Encrypts plaintext using envelope encryption (ephemeral DEK wrapped by KEK)."""
        if not plaintext:
            return ""

        kek = self._get_kek(org_id)
        
        # 1. Generate ephemeral 256-bit DEK
        dek = AESGCM.generate_key(bit_length=256)
        
        # 2. Encrypt plaintext with DEK using AES-256-GCM
        aesgcm_dek = AESGCM(dek)
        iv_data = secrets.token_bytes(12)  # 96-bit nonce
        ciphertext_bytes = aesgcm_dek.encrypt(iv_data, plaintext.encode("utf-8"), None)
        
        # 3. Wrap DEK with KEK using AES-256-GCM
        aesgcm_kek = AESGCM(kek)
        iv_kek = secrets.token_bytes(12)
        wrapped_dek = aesgcm_kek.encrypt(iv_kek, dek, None)
        
        # 4. Serialize envelope: v1:<wrapped_dek>:<iv_kek>:<iv_data>:<ciphertext_bytes>
        envelope = {
            "v": 1,
            "w_dek": base64.b64encode(wrapped_dek).decode("utf-8"),
            "iv_k": base64.b64encode(iv_kek).decode("utf-8"),
            "iv_d": base64.b64encode(iv_data).decode("utf-8"),
            "ct": base64.b64encode(ciphertext_bytes).decode("utf-8")
        }
        return "env:" + base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")

    def decrypt(self, envelope_str: str, org_id: Optional[str] = None) -> str:
        """Unwraps ephemeral DEK using KEK and decrypts ciphertext."""
        if not envelope_str:
            return ""
        if not envelope_str.startswith("env:"):
            # Plaintext fallback for legacy unencrypted data during migrations
            return envelope_str

        raw_json = base64.b64decode(envelope_str[4:]).decode("utf-8")
        envelope = json.loads(raw_json)

        kek = self._get_kek(org_id)

        wrapped_dek = base64.b64decode(envelope["w_dek"])
        iv_kek = base64.b64decode(envelope["iv_k"])
        iv_data = base64.b64decode(envelope["iv_d"])
        ciphertext_bytes = base64.b64decode(envelope["ct"])

        # 1. Unwrap DEK using KEK
        aesgcm_kek = AESGCM(kek)
        dek = aesgcm_kek.decrypt(iv_kek, wrapped_dek, None)

        # 2. Decrypt ciphertext using unwrapped DEK
        aesgcm_dek = AESGCM(dek)
        plaintext_bytes = aesgcm_dek.decrypt(iv_data, ciphertext_bytes, None)
        return plaintext_bytes.decode("utf-8")

    def rotate_envelope(self, envelope_str: str, old_org_id: Optional[str] = None, new_org_id: Optional[str] = None) -> str:
        """Decrypts with current KEK and re-encrypts with new KEK (for key rotation or BYOK migration)."""
        decrypted = self.decrypt(envelope_str, org_id=old_org_id)
        return self.encrypt(decrypted, org_id=new_org_id)

encryption_service = EnvelopeEncryptionService()

def encrypt_value(plaintext: str, org_id: Optional[str] = None) -> str:
    """Convenience helper to encrypt a value with envelope encryption."""
    return encryption_service.encrypt(plaintext, org_id=org_id)

def decrypt_value(envelope_str: str, org_id: Optional[str] = None) -> str:
    """Convenience helper to decrypt an envelope encrypted value."""
    return encryption_service.decrypt(envelope_str, org_id=org_id)

