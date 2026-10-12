import ipaddress
import socket
import urllib.parse
from fastapi import HTTPException, status

def validate_outbound_url_ssrf(url: str) -> None:
    """Validates that a URL is safe for outbound server-side requests.
    Strictly forbids private IP ranges, loopback addresses, link-local (cloud metadata like 169.254.169.254),
    and non-HTTP/HTTPS schemes.
    """
    if not url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL cannot be empty."
        )

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed URL format."
        )

    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted."
        )

    host = parsed.hostname
    if not host:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL must contain a valid hostname."
        )

    # Check for direct IP address literal
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Target address '{host}' is prohibited. Private, loopback, and cloud metadata addresses are forbidden (SSRF protection)."
            )
        return
    except ValueError:
        pass  # Host is a domain name, proceed to DNS resolution

    # Resolve domain to all IP addresses and check each
    try:
        addr_info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unable to resolve host '{host}'."
        )

    for _, _, _, _, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            resolved_ip = ipaddress.ip_address(ip_str)
            if (resolved_ip.is_private or resolved_ip.is_loopback or
                resolved_ip.is_link_local or resolved_ip.is_reserved or
                resolved_ip.is_multicast or resolved_ip.is_unspecified):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Host '{host}' resolves to protected IP '{ip_str}'. Outbound request rejected (SSRF protection)."
                )
        except ValueError:
            continue
