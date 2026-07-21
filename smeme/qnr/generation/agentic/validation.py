"""URL validation for generation brief (OWASP-aligned).

Validates include_domains textarea: one URL per line or comma-separated.
Allowlists http/https only; rejects javascript:, data:, file:, etc.
Per §4.6: blocks private IPs, link-local, cloud metadata (SSRF protection).
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger("smeme.qnr.generation.agentic")

# Max length per URL (OWASP / RFC 7230 practical limit)
MAX_URL_LENGTH = 2048

# Allowed schemes (allowlist, not denylist)
ALLOWED_SCHEMES = frozenset({"http", "https"})

# SSRF: blocked IP ranges (per plan §4.6)
_BLOCKED_IPV4_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),  # Private
    ipaddress.ip_network("172.16.0.0/12"),  # Private
    ipaddress.ip_network("192.168.0.0/16"),  # Private
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local (includes cloud metadata)
    ipaddress.ip_network("127.0.0.0/8"),  # Localhost
]
_CLOUD_METADATA_IP = ipaddress.ip_address("169.254.169.254")
_BLOCKED_IPV6 = {
    ipaddress.ip_address("::1"),
    ipaddress.ip_address("::ffff:127.0.0.1"),
}


def _is_ip_blocked(ip_str: str) -> bool:
    """Return True if the IP is in the SSRF blocklist."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Invalid IP, fail closed
    if ip.version == 6:
        return ip in _BLOCKED_IPV6 or ip.is_loopback
    for net in _BLOCKED_IPV4_NETWORKS:
        if ip in net:
            return True
    return ip == _CLOUD_METADATA_IP


def resolve_and_validate_url_host(url: str) -> tuple[bool, str | None]:
    """
    Resolve hostname to IP(s) and reject if any is blocked (SSRF).

    Returns (True, None) if allowed, (False, reason) if blocked.
    """
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip()
        if not host:
            return False, "No hostname in URL"
        # Resolve hostname to IPs
        try:
            addrinfos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except (socket.gaierror, OSError) as e:
            return False, f"Could not resolve hostname ({e})"
        for info in addrinfos:
            # info is (family, type, proto, canonname, sockaddr)
            addr = info[4][0] if isinstance(info[4], tuple) else str(info[4])
            if _is_ip_blocked(addr):
                return False, "URL resolves to a blocked address (private/local)"
        return True, None
    except Exception as e:
        return False, str(e)


def parse_and_validate_include_urls(raw: str) -> tuple[list[str], list[str]]:
    """Parse include_domains string and return validated and invalid URLs.

    - Splits by newline and comma
    - Allows http:// and https:// only
    - Rejects javascript:, data:, file:, etc.
    - Enforces max length per URL
    - Returns (valid_urls, invalid_descriptions)

    Returns:
        Tuple of (list of valid URL strings, list of invalid URL descriptions for feedback)
    """
    if not raw or not raw.strip():
        return ([], [])

    lines: list[str] = []
    for part in raw.replace(",", "\n").split("\n"):
        u = part.strip()
        if u:
            lines.append(u)

    valid: list[str] = []
    invalid: list[str] = []

    for u in lines:
        if len(u) > MAX_URL_LENGTH:
            invalid.append(f"{u[:50]}... (exceeds {MAX_URL_LENGTH} chars)")
            continue
        try:
            parsed = urlparse(u)
            scheme = (parsed.scheme or "").lower()
            if scheme not in ALLOWED_SCHEMES:
                invalid.append(f"{u[:80]} (scheme '{parsed.scheme or 'none'}' not allowed)")
                continue
            # Basic structure: has netloc for http(s)
            if not parsed.netloc and scheme in ALLOWED_SCHEMES:
                invalid.append(f"{u[:80]} (invalid URL structure)")
                continue
            # SSRF: block private/local IPs (per plan §4.6)
            ok, reason = resolve_and_validate_url_host(u)
            if not ok:
                invalid.append(f"{u[:80]} ({reason})")
                continue
            valid.append(u)
        except Exception as e:
            invalid.append(f"{u[:80]} ({e})")

    if invalid:
        logger.info(
            "Dropped invalid include URLs",
            extra={"invalid_count": len(invalid), "invalid_sample": invalid[:5]},
        )

    return (valid, invalid)
