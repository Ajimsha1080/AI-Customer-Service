import base64
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from lxml import etree
import signxml

logger = logging.getLogger("hospitality_agent_cloud.security.saml")

# In-memory replay cache with TTL cleanup
_SEEN_ASSERTION_IDS: Dict[str, datetime] = {}

class SAMLValidationError(Exception):
    """Raised when SAML assertion fails cryptographic or claim validation."""
    pass

def _clean_replay_cache():
    now = datetime.now(timezone.utc)
    expired = [k for k, exp in _SEEN_ASSERTION_IDS.items() if exp <= now]
    for k in expired:
        _SEEN_ASSERTION_IDS.pop(k, None)

async def check_and_record_assertion_id(assertion_id: str, expires_at: datetime) -> bool:
    """Checks if assertion ID has been processed; records it if fresh.
    Returns True if fresh, False if replayed.
    """
    if not assertion_id:
        return False

    # 1. Try Redis if available
    try:
        from apps.api.config import settings
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=0.3)
        ttl = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
        # SET key 1 NX EX ttl
        ok = await r.set(f"saml_replay:{assertion_id}", "1", nx=True, ex=ttl)
        await r.aclose()
        if not ok:
            return False
    except Exception:
        # Fall back to in-memory replay cache
        pass

    _clean_replay_cache()
    if assertion_id in _SEEN_ASSERTION_IDS:
        return False
    _SEEN_ASSERTION_IDS[assertion_id] = expires_at
    return True

def _format_iso8601(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
    """Cryptographically validates a SAML 2.0 Response XML document.
    Validates:
    - XML-DSig signature against idp_x509_cert
    - Issuer
    - Audience restriction
    - Destination
    - Timestamps (NotBefore, NotOnOrAfter)
    - InResponseTo
    - Assertion replay
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

    # Validate XML-DSig Signature
    if not idp_x509_cert:
        raise SAMLValidationError("Organization has no configured IdP X.509 certificate for signature validation.")

    # Normalize PEM certificate format if needed
    cert_clean = idp_x509_cert.strip()
    if not cert_clean.startswith("-----BEGIN CERTIFICATE-----"):
        cert_clean = f"-----BEGIN CERTIFICATE-----\n{cert_clean}\n-----END CERTIFICATE-----"

    # Find signed element: either the Response or Assertion
    verifier = signxml.XMLVerifier()
    try:
        verified_data = verifier.verify(root, x509_cert=cert_clean)
    except Exception as e:
        raise SAMLValidationError(f"SAML XML signature verification failed: {e}")

    # Namespaces
    namespaces = {
        "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
        "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
        "ds": "http://www.w3.org/2000/09/xmldsig#"
    }

    # Find Assertion element
    assertion = root.find(".//saml:Assertion", namespaces)
    if assertion is None:
        raise SAMLValidationError("No SAML Assertion found in response.")

    # 1. Assertion ID and InResponseTo
    assertion_id = assertion.get("ID") or root.get("ID")
    if not assertion_id:
        raise SAMLValidationError("SAML assertion is missing required ID attribute.")

    resp_in_response_to = root.get("InResponseTo")
    subject_conf = assertion.find(".//saml:SubjectConfirmationData", namespaces)
    subj_in_response_to = subject_conf.get("InResponseTo") if subject_conf is not None else None
    actual_in_response_to = resp_in_response_to or subj_in_response_to

    if expected_in_response_to and actual_in_response_to:
        if actual_in_response_to != expected_in_response_to:
            raise SAMLValidationError(
                f"SAML InResponseTo mismatch: expected '{expected_in_response_to}', got '{actual_in_response_to}'."
            )

    # 2. Issuer verification
    issuer_elem = assertion.find("saml:Issuer", namespaces)
    if issuer_elem is None:
        issuer_elem = root.find("saml:Issuer", namespaces)
    actual_issuer = issuer_elem.text.strip() if issuer_elem is not None and issuer_elem.text else ""

    if expected_issuer and actual_issuer != expected_issuer:
        raise SAMLValidationError(
            f"SAML Issuer mismatch: expected '{expected_issuer}', got '{actual_issuer}'."
        )

    # 3. Destination verification
    destination = root.get("Destination")
    if destination and expected_recipient:
        # Check that destination matches expected callback recipient URL
        if destination.rstrip("/") != expected_recipient.rstrip("/"):
            raise SAMLValidationError(
                f"SAML Destination mismatch: expected '{expected_recipient}', got '{destination}'."
            )

    # 4. Conditions verification (NotBefore, NotOnOrAfter, Audience)
    conditions = assertion.find("saml:Conditions", namespaces)
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
        # If NotOnOrAfter not specified on conditions, check subject confirmation
        if subject_conf is not None and subject_conf.get("NotOnOrAfter"):
            not_on_or_after = _parse_iso8601(subject_conf.get("NotOnOrAfter"))
            if (now - skew) >= not_on_or_after:
                raise SAMLValidationError("SAML SubjectConfirmation has expired.")
        else:
            not_on_or_after = now + timedelta(minutes=5)

    # Audience check
    if expected_audience:
        audience_elems = conditions.findall(".//saml:Audience", namespaces)
        audiences = [a.text.strip() for a in audience_elems if a.text]
        if audiences and expected_audience not in audiences:
            raise SAMLValidationError(
                f"SAML Audience mismatch: expected '{expected_audience}' in {audiences}."
            )

    # 5. Extract Subject Email & Attributes
    email = None
    # Check NameID
    name_id = assertion.find(".//saml:Subject/saml:NameID", namespaces)
    if name_id is not None and name_id.text and "@" in name_id.text:
        email = name_id.text.strip()

    # Check Attributes
    attributes: Dict[str, Any] = {}
    attr_elems = assertion.findall(".//saml:AttributeStatement/saml:Attribute", namespaces)
    for attr in attr_elems:
        name = attr.get("Name", "")
        friendly_name = attr.get("FriendlyName", "")
        vals = [v.text.strip() for v in attr.findall("saml:AttributeValue", namespaces) if v.text]
        val = vals[0] if len(vals) == 1 else vals
        if name:
            attributes[name] = val
        if friendly_name:
            attributes[friendly_name] = val

        # Infer email from well-known attribute names
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

def create_signed_saml_response(
    issuer: str,
    audience: str,
    recipient: str,
    in_response_to: str,
    email: str,
    full_name: str,
    private_key_pem: str,
    cert_pem: str,
    not_before_delta_seconds: int = -60,
    not_on_or_after_delta_seconds: int = 300,
    assertion_id: Optional[str] = None,
    sign: bool = True
) -> str:
    """Helper used to generate real signed SAML 2.0 assertions for test IdP."""
    now = datetime.now(timezone.utc)
    not_before = _format_iso8601(now + timedelta(seconds=not_before_delta_seconds))
    not_on_or_after = _format_iso8601(now + timedelta(seconds=not_on_or_after_delta_seconds))
    issue_instant = _format_iso8601(now)
    resp_id = f"_{uuid.uuid4().hex}"
    a_id = assertion_id or f"_{uuid.uuid4().hex}"

    xml_template = f"""<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"
    xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"
    ID="{resp_id}"
    InResponseTo="{in_response_to}"
    Version="2.0"
    IssueInstant="{issue_instant}"
    Destination="{recipient}">
    <saml:Issuer>{issuer}</saml:Issuer>
    <samlp:Status>
        <samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>
    </samlp:Status>
    <saml:Assertion ID="{a_id}" Version="2.0" IssueInstant="{issue_instant}">
        <saml:Issuer>{issuer}</saml:Issuer>
        <saml:Subject>
            <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{email}</saml:NameID>
            <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
                <saml:SubjectConfirmationData InResponseTo="{in_response_to}"
                    Recipient="{recipient}"
                    NotOnOrAfter="{not_on_or_after}"/>
            </saml:SubjectConfirmation>
        </saml:Subject>
        <saml:Conditions NotBefore="{not_before}" NotOnOrAfter="{not_on_or_after}">
            <saml:AudienceRestriction>
                <saml:Audience>{audience}</saml:Audience>
            </saml:AudienceRestriction>
        </saml:Conditions>
        <saml:AttributeStatement>
            <saml:Attribute Name="email">
                <saml:AttributeValue>{email}</saml:AttributeValue>
            </saml:Attribute>
            <saml:Attribute Name="full_name">
                <saml:AttributeValue>{full_name}</saml:AttributeValue>
            </saml:Attribute>
        </saml:AttributeStatement>
    </saml:Assertion>
</samlp:Response>"""

    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    root = etree.fromstring(xml_template.encode(), parser=parser)

    if sign:
        signer = signxml.XMLSigner(
            method=signxml.methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256"
        )
        # Sign the Assertion element or Response
        assertion_elem = root.find(".//saml:Assertion", {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"})
        signed_root = signer.sign(root, key=private_key_pem, cert=cert_pem)
        final_xml = etree.tostring(signed_root, encoding="utf-8")
    else:
        final_xml = etree.tostring(root, encoding="utf-8")

    return base64.b64encode(final_xml).decode("utf-8")
