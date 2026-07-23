"""Unit tests for URL validation (OWASP + SSRF).

Per docs/planning/decision_tree-generation-ux-refinement.md §4.6.
"""

from unittest.mock import patch

from smeme.decision_tree.generation.agentic.validation import (
    parse_and_validate_include_urls,
    resolve_and_validate_url_host,
)


class TestResolveAndValidateUrlHost:
    """SSRF: block private IPs, link-local, localhost."""

    def test_localhost_blocked(self):
        # 127.0.0.1 is in 127.0.0.0/8
        ok, reason = resolve_and_validate_url_host("http://127.0.0.1/")
        assert ok is False
        assert "blocked" in (reason or "").lower() or "private" in (reason or "").lower()

    def test_private_ip_blocked(self):
        with patch("socket.getaddrinfo") as mock:
            mock.return_value = [(None, None, None, None, ("192.168.1.1", 0))]
            ok, reason = resolve_and_validate_url_host("http://internal.example/")
            assert ok is False

    def test_cloud_metadata_ip_blocked(self):
        with patch("socket.getaddrinfo") as mock:
            mock.return_value = [(None, None, None, None, ("169.254.169.254", 0))]
            ok, reason = resolve_and_validate_url_host("http://metadata/")
            assert ok is False

    def test_public_ip_allowed(self):
        with patch("socket.getaddrinfo") as mock:
            mock.return_value = [(None, None, None, None, ("93.184.216.34", 0))]  # example.com
            ok, reason = resolve_and_validate_url_host("http://example.com/")
            assert ok is True
            assert reason is None

    def test_ipv6_localhost_blocked(self):
        with patch("socket.getaddrinfo") as mock:
            mock.return_value = [(None, None, None, None, ("::1", 0, 0, 0))]
            ok, reason = resolve_and_validate_url_host("http://[::1]/")
            assert ok is False


class TestParseAndValidateIncludeUrls:
    """Full validation including SSRF."""

    def test_localhost_rejected_in_parse(self):
        valid, invalid = parse_and_validate_include_urls("http://127.0.0.1/")
        assert valid == []
        assert len(invalid) >= 1
        assert any("blocked" in i.lower() or "private" in i.lower() for i in invalid)

    def test_valid_url_accepted(self):
        with patch("smeme.decision_tree.generation.agentic.validation.resolve_and_validate_url_host") as mock:
            mock.return_value = (True, None)
            valid, invalid = parse_and_validate_include_urls("https://example.com/")
            assert "https://example.com/" in valid
            assert invalid == []
