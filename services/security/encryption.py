import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from apps.api.config import settings

def _get_fernet_key() -> bytes:
    """Derives a deterministic 32-byte URL-safe base64 key from system SECRET_KEY."""
    raw = (getattr(settings, "ENCRYPTION_KEY", None) or settings.SECRET_KEY).encode("utf-8")
    derived_32_bytes = hashlib.sha256(raw).digest()
    return base64.urlsafe_b64encode(derived_32_bytes)

def encrypt_value(secret: Optional[str]) -> Optional[str]:
    """Encrypts a plaintext string at rest using Fernet (AES-128-CBC + HMAC-SHA256)."""
    if not secret:
        return None
    f = Fernet(_get_fernet_key())
    return f.encrypt(secret.encode("utf-8")).decode("utf-8")

def decrypt_value(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypts a ciphertext back to plaintext. Returns empty string on failure."""
    if not ciphertext:
        return None
    try:
        f = Fernet(_get_fernet_key())
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        return None
