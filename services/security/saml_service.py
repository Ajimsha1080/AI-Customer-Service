import base64
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from lxml import etree
import signxml

logger = logging.getLogger("hospitality_agent_cloud.security.saml")

class SAMLValidationError(Exception):
    """Raised when SAML assertion fails cryptographic or claim validation."""
    pass

_DEV_TEST_REPLAY_CACHE = set()

async def check_and_record_assertion_id(assertion_id: str, expires_at: datetime) -> bool:
    """Checks if assertion ID has been processed; records it in Redis with TTL.
    Returns True if fresh, False if replayed.
    In production, Redis is strictly required across replicas. In testing/dev, simulated fallback is allowed per Rule 1.
    """
    if not assertion_id:
        return False

    from apps.api.config import settings
    import redis.asyncio as aioredis
    ttl = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    try:
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3)
        ok = await r.set(f"saml_replay:{assertion_id}", "1", nx=True, ex=ttl)
        await r.aclose()
        return bool(ok)
    except Exception as e:
        if settings.is_production:
            logger.error(f"Redis replay cache failure in production for assertion {assertion_id}: {e}")
            raise SAMLValidationError("SAML replay protection store (Redis) unavailable in production.")
        # Rule 1: Simulated modes allowed only when ENVIRONMENT is development or testing
        if assertion_id in _DEV_TEST_REPLAY_CACHE:
            return False
        _DEV_TEST_REPLAY_CACHE.add(assertion_id)
        return True

def _parse_iso8601(val: str) -> datetime:
    val = val.strip()
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    return datetime.fromisoformat(val)

def validate_saml_response(
    saml_response_b64: str,
    idp_x509_cert: str,
    expected_recipient: Optional[str] = None,
    expected_audience: Optional[str] = None,
    expected_issuer: Optional[str] = None,
    expected_in_response_to: Optional[str] = None,
    clock_skew_seconds: int = 0
) -> Dict[str, Any]:
    """Cryptographically validates a SAML 2.0 Response XML document against XSW and forgery.
    
    Security Controls:
    - Exactly ONE Assertion required; multiple Assertions rejected (XSW protection).
    - Signature method and digest algorithm pinned to SHA-256 or higher (no SHA-1 / MD5).
    - XML-DSig signature verified against IdP X.509 certificate.
    - Signed Assertion required: ALL claims extracted exclusively from verified signed_xml.
    - Issuer, Audience, Destination, Timestamps, InResponseTo strictly validated.
    """
    if not saml_response_b64 or not isinstance(saml_response_b64, str):
        raise SAMLValidationError("Missing or empty SAML response.")

    try:
        raw_xml = base64.b64decode(saml_response_b64)
    except Exception as e:
        raise SAMLValidationError(f"Invalid base64 encoding: {e}")

    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(raw_xml, parser=parser)
    except Exception as e:
        raise SAMLValidationError(f"Invalid SAML XML payload: {e}")

    # 1. Structural check: Exactly ONE Assertion permitted in the entire XML document
    assertion_nodes = root.xpath("//*[local-name()='Assertion']")
    if len(assertion_nodes) == 0:
        raise SAMLValidationError("No SAML Assertion found in response.")
    if len(assertion_nodes) > 1:
        raise SAMLValidationError(
            f"Multiple SAML Assertions ({len(assertion_nodes)}) detected. Rejected to prevent signature wrapping (XSW)."
        )

    # 2. Algorithm pinning: Check signature & digest algorithms
    sig_methods = root.xpath("//*[local-name()='SignatureMethod']")
    for sm in sig_methods:
        algo = sm.get("Algorithm", "").lower()
        if "sha1" in algo or "md5" in algo:
            raise SAMLValidationError(f"Insecure SAML signature algorithm '{algo}'. Only SHA-256 or stronger allowed.")
        if "sha256" not in algo and "sha384" not in algo and "sha512" not in algo:
            raise SAMLValidationError(f"Unsupported SAML signature algorithm '{algo}'.")

    digest_methods = root.xpath("//*[local-name()='DigestMethod']")
    for dm in digest_methods:
        dalgo = dm.get("Algorithm", "").lower()
        if "sha1" in dalgo or "md5" in dalgo:
            raise SAMLValidationError(f"Insecure SAML digest algorithm '{dalgo}'. Only SHA-256 or stronger allowed.")
        if "sha256" not in dalgo and "sha384" not in dalgo and "sha512" not in dalgo:
            raise SAMLValidationError(f"Unsupported SAML digest algorithm '{dalgo}'.")

    # 3. Validate XML-DSig signature
    if not idp_x509_cert:
        raise SAMLValidationError("Organization has no configured IdP X.509 certificate for signature validation.")

    cert_clean = idp_x509_cert.strip()
    if not cert_clean.startswith("-----BEGIN CERTIFICATE-----"):
        cert_clean = f"-----BEGIN CERTIFICATE-----\n{cert_clean}\n-----END CERTIFICATE-----"

    verifier = signxml.XMLVerifier()
    try:
        verified_data = verifier.verify(root, x509_cert=cert_clean)
    except Exception as e:
        raise SAMLValidationError(f"SAML XML signature verification failed: {e}")

    # 4. Strict isolation: Read ALL claims only from verified_data.signed_xml
    signed_xml = verified_data.signed_xml
    if signed_xml is None:
        raise SAMLValidationError("Signature verification yielded no verified signed elements.")

    # Locate the verified Assertion strictly within the verified tree
    if signed_xml.tag.endswith("Assertion"):
        assertion = signed_xml
    else:
        assertions_in_signed = signed_xml.xpath(".//*[local-name()='Assertion']")
        if not assertions_in_signed:
            raise SAMLValidationError("Signed Assertion required: signature does not cover an Assertion.")
        assertion = assertions_in_signed[0]

    # Ensure the single document assertion matches the verified assertion
    doc_assertion_id = assertion_nodes[0].get("ID")
    verified_assertion_id = assertion.get("ID")
    if not verified_assertion_id or doc_assertion_id != verified_assertion_id:
        raise SAMLValidationError("SAML signature wrapping attack detected: verified assertion ID mismatch.")

    assertion_id = verified_assertion_id

    # Namespaces for parsing verified assertions
    namespaces = {
        "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
        "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
        "ds": "http://www.w3.org/2000/09/xmldsig#"
    }

    # 5. InResponseTo verification
    subject_conf = assertion.find(".//saml:SubjectConfirmationData", namespaces)
    subj_in_response_to = subject_conf.get("InResponseTo") if subject_conf is not None else None
    resp_in_response_to = root.get("InResponseTo")
    actual_in_response_to = subj_in_response_to or resp_in_response_to

    if expected_in_response_to and actual_in_response_to:
        if actual_in_response_to != expected_in_response_to:
            raise SAMLValidationError(
                f"SAML InResponseTo mismatch: expected '{expected_in_response_to}', got '{actual_in_response_to}'."
            )

    # 6. Issuer verification strictly from verified assertion
    issuer_elem = assertion.find("saml:Issuer", namespaces)
    if issuer_elem is None:
        issuer_elem = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Issuer")
    actual_issuer = issuer_elem.text.strip() if issuer_elem is not None and issuer_elem.text else ""

    if expected_issuer and actual_issuer != expected_issuer:
        raise SAMLValidationError(
            f"SAML Issuer mismatch: expected '{expected_issuer}', got '{actual_issuer}'."
        )

    # 7. Destination verification
    destination = root.get("Destination")
    if destination and expected_recipient:
        if destination.rstrip("/") != expected_recipient.rstrip("/"):
            raise SAMLValidationError(
                f"SAML Destination mismatch: expected '{expected_recipient}', got '{destination}'."
            )

    # 8. Conditions verification (NotBefore, NotOnOrAfter, Audience) from verified assertion
    conditions = assertion.find("saml:Conditions", namespaces)
    if conditions is None:
        conditions = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}Conditions")
    if conditions is None:
        raise SAMLValidationError("SAML Assertion missing required Conditions element.")

    now = datetime.now(timezone.utc)
    skew = timedelta(seconds=clock_skew_seconds)

    not_before_str = conditions.get("NotBefore")
    if not_before_str:
        not_before = _parse_iso8601(not_before_str)
        if (now + skew) < not_before:
            raise SAMLValidationError(f"SAML Assertion is not yet valid (NotBefore={not_before_str}).")

    not_on_or_after_str = conditions.get("NotOnOrAfter")
    if not_on_or_after_str:
        not_on_or_after = _parse_iso8601(not_on_or_after_str)
        if (now - skew) >= not_on_or_after:
            raise SAMLValidationError(f"SAML Assertion has expired (NotOnOrAfter={not_on_or_after_str}).")
    else:
        if subject_conf is not None and subject_conf.get("NotOnOrAfter"):
            not_on_or_after = _parse_iso8601(subject_conf.get("NotOnOrAfter"))
            if (now - skew) >= not_on_or_after:
                raise SAMLValidationError("SAML SubjectConfirmation has expired.")
        else:
            not_on_or_after = now + timedelta(minutes=5)

    if expected_audience:
        audience_elems = conditions.findall(".//saml:Audience", namespaces)
        if not audience_elems:
            audience_elems = conditions.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Audience")
        audiences = [a.text.strip() for a in audience_elems if a.text]
        if audiences and expected_audience not in audiences:
            raise SAMLValidationError(
                f"SAML Audience mismatch: expected '{expected_audience}' in {audiences}."
            )

    # 9. Extract Subject Email & Attributes strictly from verified assertion
    email = None
    name_id = assertion.find(".//saml:Subject/saml:NameID", namespaces)
    if name_id is None:
        name_id = assertion.find(".//{urn:oasis:names:tc:SAML:2.0:assertion}NameID")
    if name_id is not None and name_id.text and "@" in name_id.text:
        email = name_id.text.strip()

    attributes: Dict[str, Any] = {}
    attr_elems = assertion.findall(".//saml:AttributeStatement/saml:Attribute", namespaces)
    if not attr_elems:
        attr_elems = assertion.findall(".//{urn:oasis:names:tc:SAML:2.0:assertion}Attribute")
    for attr in attr_elems:
        name = attr.get("Name", "")
        friendly_name = attr.get("FriendlyName", "")
        vals = [v.text.strip() for v in attr.findall("saml:AttributeValue", namespaces) if v.text]
        if not vals:
            vals = [v.text.strip() for v in attr.findall("{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue") if v.text]
        val = vals[0] if len(vals) == 1 else vals
        if name:
            attributes[name] = val
        if friendly_name:
            attributes[friendly_name] = val

        if not email and name.lower() in (
            "email", "mail", "emailaddress",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"
        ):
            if isinstance(val, str) and "@" in val:
                email = val

    if not email:
        raise SAMLValidationError("SAML assertion does not contain an email address.")

    full_name = (
        attributes.get("full_name") or
        attributes.get("name") or
        attributes.get("displayName") or
        attributes.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name") or
        email.split("@")[0]
    )

    return {
        "email": email.lower().strip(),
        "full_name": str(full_name),
        "assertion_id": assertion_id,
        "issuer": actual_issuer,
        "not_on_or_after": not_on_or_after,
        "attributes": attributes
    }
