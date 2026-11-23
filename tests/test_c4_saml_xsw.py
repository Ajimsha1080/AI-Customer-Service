import base64
import pytest
from datetime import datetime, timezone, timedelta
from lxml import etree
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization, hashes
from cryptography import x509
from cryptography.x509.oid import NameOID

from services.security.saml_service import (
    validate_saml_response,
    check_and_record_assertion_id,
    SAMLValidationError
)
from tests.saml_test_helpers import create_signed_saml_response

@pytest.fixture(scope="module")
def saml_test_crypto():
    """Generates RSA keypair and self-signed X.509 cert for SAML testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test SAML IdP"),
        x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.com"),
    ])
    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.now(timezone.utc) - timedelta(days=1)
    ).not_valid_after(
        datetime.now(timezone.utc) + timedelta(days=365)
    ).sign(key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
    return {"private_key": private_key_pem, "cert": cert_pem}

def test_c4_valid_signed_saml_response(saml_test_crypto):
    """Test standard valid signed SAML assertion."""
    xml_b64 = create_signed_saml_response(
        issuer="https://idp.example.com",
        audience="https://sp.example.com",
        recipient="https://sp.example.com/callback",
        in_response_to="req_12345",
        email="alice@example.com",
        full_name="Alice Smith",
        private_key_pem=saml_test_crypto["private_key"],
        cert_pem=saml_test_crypto["cert"],
    )
    result = validate_saml_response(
        saml_response_b64=xml_b64,
        idp_x509_cert=saml_test_crypto["cert"],
        expected_recipient="https://sp.example.com/callback",
        expected_audience="https://sp.example.com",
        expected_issuer="https://idp.example.com",
        expected_in_response_to="req_12345"
    )
    assert result["email"] == "alice@example.com"
    assert result["full_name"] == "Alice Smith"

def test_c4_xsw_multiple_assertions_rejected(saml_test_crypto):
    """Test XSW attack variant: Injecting a second forged assertion."""
    valid_b64 = create_signed_saml_response(
        issuer="https://idp.example.com",
        audience="https://sp.example.com",
        recipient="https://sp.example.com/callback",
        in_response_to="req_12345",
        email="alice@example.com",
        full_name="Alice Smith",
        private_key_pem=saml_test_crypto["private_key"],
        cert_pem=saml_test_crypto["cert"],
    )
    xml_bytes = base64.b64decode(valid_b64)
    root = etree.fromstring(xml_bytes)

    # Clone the assertion, tamper email, and append as second assertion
    assertion = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    forged_assertion = etree.fromstring(etree.tostring(assertion))
    forged_assertion.set("ID", "_forged_assertion_id")
    name_id = forged_assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    if name_id is not None:
        name_id.text = "attacker@example.com"
    root.append(forged_assertion)

    tampered_b64 = base64.b64encode(etree.tostring(root)).decode("utf-8")
    with pytest.raises(SAMLValidationError, match="Multiple SAML Assertions"):
        validate_saml_response(
            saml_response_b64=tampered_b64,
            idp_x509_cert=saml_test_crypto["cert"],
            expected_recipient="https://sp.example.com/callback",
            expected_audience="https://sp.example.com"
        )

def test_c4_xsw_wrapped_assertion_mismatch_rejected(saml_test_crypto):
    """Test XSW attack where an unsigned assertion is inserted at root and signed assertion placed in extension."""
    valid_b64 = create_signed_saml_response(
        issuer="https://idp.example.com",
        audience="https://sp.example.com",
        recipient="https://sp.example.com/callback",
        in_response_to="req_12345",
        email="alice@example.com",
        full_name="Alice Smith",
        private_key_pem=saml_test_crypto["private_key"],
        cert_pem=saml_test_crypto["cert"],
    )
    xml_bytes = base64.b64decode(valid_b64)
    root = etree.fromstring(xml_bytes)

    # Tamper document assertion ID so it does not match signed assertion ID
    assertion = root.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Assertion")
    assertion.set("ID", "_evil_modified_id")

    tampered_b64 = base64.b64encode(etree.tostring(root)).decode("utf-8")
    with pytest.raises(SAMLValidationError):
        validate_saml_response(
            saml_response_b64=tampered_b64,
            idp_x509_cert=saml_test_crypto["cert"]
        )

def test_c4_insecure_sha1_rejected(saml_test_crypto):
    """Test that insecure digest algorithms (SHA-1) are rejected."""
    valid_b64 = create_signed_saml_response(
        issuer="https://idp.example.com",
        audience="https://sp.example.com",
        recipient="https://sp.example.com/callback",
        in_response_to="req_12345",
        email="alice@example.com",
        full_name="Alice Smith",
        private_key_pem=saml_test_crypto["private_key"],
        cert_pem=saml_test_crypto["cert"],
    )
    xml_bytes = base64.b64decode(valid_b64)
    tampered = xml_bytes.replace(
        b"http://www.w3.org/2001/04/xmlenc#sha256",
        b"http://www.w3.org/2000/09/xmldsig#sha1"
    )
    insecure_b64 = base64.b64encode(tampered).decode("utf-8")
    with pytest.raises(SAMLValidationError, match="Insecure SAML"):
        validate_saml_response(
            saml_response_b64=insecure_b64,
            idp_x509_cert=saml_test_crypto["cert"]
        )

@pytest.mark.asyncio
async def test_c4_replay_cache_deduplication():
    """Test that assertion ID replay detection rejects duplicate submissions."""
    a_id = f"_unique_test_assertion_{datetime.now().timestamp()}"
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    first = await check_and_record_assertion_id(a_id, exp)
    assert first is True
    
    second = await check_and_record_assertion_id(a_id, exp)
    assert second is False
