"""SSRF defence — IP-blocked-network checks for outbound HTTP fetches.

Extracted from ``content/fetch.py`` per plan
``docs/plans/2026-05-14-007-feat-url-content-fetch-gate-plan.md``.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.error import URLError
from urllib.request import build_opener, HTTPRedirectHandler, OpenerDirector, Request

from backlink_publisher._util.url import safe_urlparse

_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("168.63.129.16/32"),  # Azure wireserver (DHCP, key mgmt, health probes)
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("2001::/32"),
    ipaddress.ip_network("2002::/16"),
)


# Subset of _BLOCKED_NETWORKS that ``allow_private=True`` deliberately permits:
# RFC1918 private ranges + loopback. These are where operator self-hosted blog
# endpoints and local AI gateways live. Everything else in _BLOCKED_NETWORKS
# stays blocked even under allow_private — critically 169.254.0.0/16 and
# 168.63.129.16 (cloud metadata / Azure wireserver), CGNAT, link-local, and the
# documentation/benchmark ranges. allow_private relaxes the LAN guard, NOT the
# metadata-exfiltration guard.
_PRIVATE_OK_NETWORKS: frozenset[ipaddress.IPv4Network | ipaddress.IPv6Network] = frozenset(
    {
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("::1/128"),
    }
)


def _is_blocked_ip(ip_text: str, allow_private: bool = False) -> str | None:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return "invalid_ip"
    for net in _BLOCKED_NETWORKS:
        if ip.version != net.version:
            continue
        if ip in net:
            if allow_private and net in _PRIVATE_OK_NETWORKS:
                return None
            return f"blocked_ip:{net}"
    return None


def _resolve_host_ips(host: str) -> tuple[list[str], str | None]:
    if not host:
        return [], "invalid_host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return [], "dns_failure"
    except OSError:
        return [], "dns_failure"
    ips: list[str] = []
    for fam, _typ, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0] if sockaddr else None
        if ip and ip not in ips:
            ips.append(str(ip))
    if not ips:
        return [], "dns_failure"
    return ips, None


def _check_url_for_ssrf(url: str, allow_private: bool = False) -> str | None:
    # Never-raises: a malformed authority (unterminated IPv6) parses to None and
    # is treated as a *blocked* "invalid_host" (fail-closed) — _check_once calls
    # this on untrusted URLs and must never leak a ValueError. Plan 006 R3b.
    #
    # allow_private=True relaxes ONLY the RFC1918/loopback block (operator
    # self-hosted endpoints / local gateways); cloud-metadata and other
    # dangerous ranges stay blocked. Default keeps the strict fail-closed guard.
    parsed = safe_urlparse(url)
    if parsed is None:
        return "invalid_host"
    host = parsed.hostname
    if not host:
        return "invalid_host"
    try:
        ipaddress.ip_address(host)
        return _is_blocked_ip(host, allow_private=allow_private)
    except ValueError:
        pass
    ips, err = _resolve_host_ips(host)
    if err:
        return err
    for ip in ips:
        blocked = _is_blocked_ip(ip, allow_private=allow_private)
        if blocked:
            return blocked
    return None


class _SSRFSafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        # ``newurl`` is the server-controlled Location header (untrusted) — a
        # malformed authority must block the hop (URLError), not crash the
        # downgrade check with a ValueError. Guard it before any parse use.
        # Plan 006 R3c. (``req.full_url`` should not be malformed in normal
        # operation — urllib's Request(...) raises at construction on a malformed
        # URL, so a Request object with a bad full_url should not exist — the
        # safe_urlparse on it below is defence-in-depth against that assumption.)
        new_parsed = safe_urlparse(newurl)
        if new_parsed is None:
            raise URLError("ssrf_redirect:invalid_host")
        old_parsed = safe_urlparse(req.full_url)
        old_scheme = old_parsed.scheme if old_parsed is not None else ""
        if old_scheme == "https" and new_parsed.scheme == "http":
            raise URLError("ssrf_https_downgrade")
        blocked = _check_url_for_ssrf(newurl)
        if blocked:
            raise URLError(f"ssrf_redirect:{blocked}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _make_ssrf_opener(max_redirects: int = 10) -> OpenerDirector:
    """Build a fresh SSRF-safe :class:`OpenerDirector` with a redirect cap.

    ``max_redirects`` is settable per-call because the stdlib stores the cap
    on the handler instance (``max_redirections`` class attr is overridable
    on an instance). Default 10 matches the stdlib default. Used by
    ``content_fetch._check_once`` when a caller threads down a custom cap.
    """
    handler = _SSRFSafeRedirectHandler()
    setattr(handler, "max_redirections", max_redirects)
    return build_opener(handler)


_SSRF_OPENER = _make_ssrf_opener()
