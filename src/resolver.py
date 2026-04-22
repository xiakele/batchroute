from __future__ import annotations

import socket

import dns.resolver
import dns.reversename

from src.models import TracerouteResult

_reverse_cache: dict[str, str | None] = {}
_forward_cache: dict[str, str | None] = {}


def resolve_single_ip(ip: str) -> str | None:
    if ip in _reverse_cache:
        return _reverse_cache[ip]
    try:
        rev = dns.reversename.from_address(ip)
        name = str(dns.resolver.resolve(rev, "PTR")[0]).rstrip(".")
        _reverse_cache[ip] = name
        return name
    except (
        dns.resolver.NXDOMAIN,
        dns.resolver.Timeout,
        dns.resolver.NoAnswer,
        dns.exception.DNSException,
        socket.gaierror,
    ):
        _reverse_cache[ip] = None
        return None


def resolve_hostname(name: str) -> str | None:
    if name in _forward_cache:
        return _forward_cache[name]
    for rdtype in ("A", "AAAA"):
        try:
            answers = dns.resolver.resolve(name, rdtype)
            ip = str(answers[0])
            _forward_cache[name] = ip
            return ip
        except (
            dns.resolver.NXDOMAIN,
            dns.resolver.Timeout,
            dns.resolver.NoAnswer,
            dns.exception.DNSException,
            socket.gaierror,
        ):
            continue
    _forward_cache[name] = None
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
    _reverse_cache.clear()
    _forward_cache.clear()
