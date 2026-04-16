from __future__ import annotations

import socket

import dns.resolver
import dns.reversename

from src.models import TracerouteResult

_cache: dict[str, str | None] = {}


def resolve_single_ip(ip: str) -> str | None:
    if ip in _cache:
        return _cache[ip]
    try:
        rev = dns.reversename.from_address(ip)
        name = str(dns.resolver.resolve(rev, "PTR")[0]).rstrip(".")
        _cache[ip] = name
        return name
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.Timeout,
        dns.resolver.NoAnswer,
        dns.exception.DNSException,
        socket.gaierror,
    ):
        _cache[ip] = None
        return None


def resolve_result(result: TracerouteResult) -> None:
    seen_ips: set[str] = set()
    for hop in result.hops:
        if hop.ip and hop.ip not in seen_ips:
            seen_ips.add(hop.ip)
            hostname = resolve_single_ip(hop.ip)
            for h in result.hops:
                if h.ip == hop.ip:
                    h.hostname = hostname


def clear_cache() -> None:
    _cache.clear()
