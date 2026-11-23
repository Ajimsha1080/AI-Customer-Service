import base64
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from lxml import etree
import signxml

def _format_iso8601(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

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
    sign: bool = True,
    sign_assertion_only: bool = True,
    digest_algorithm: str = "sha256",
    signature_algorithm: str = "rsa-sha256"
) -> str:
    """Test IdP helper to generate signed SAML 2.0 responses for security testing."""
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
            signature_algorithm=signature_algorithm,
            digest_algorithm=digest_algorithm
        )
        if sign_assertion_only:
            assertion_elem = root.find(".//saml:Assertion", {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"})
            signed_assertion = signer.sign(assertion_elem, key=private_key_pem, cert=cert_pem)
            # replace assertion in root with signed_assertion
            parent = assertion_elem.getparent()
            idx = parent.index(assertion_elem)
            parent.remove(assertion_elem)
            parent.insert(idx, signed_assertion)
            final_xml = etree.tostring(root, encoding="utf-8")
        else:
            signed_root = signer.sign(root, key=private_key_pem, cert=cert_pem)
            final_xml = etree.tostring(signed_root, encoding="utf-8")
    else:
        final_xml = etree.tostring(root, encoding="utf-8")

    return base64.b64encode(final_xml).decode("utf-8")
