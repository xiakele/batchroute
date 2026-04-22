from __future__ import annotations

import platform
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from scapy.config import conf as scapy_conf
from scapy.layers.inet import ICMP, IP, TCP, UDP
from scapy.sendrecv import sr1

from src.config import (
    ALL_PROTOCOLS,
    DEFAULT_MAX_TTL,
    DEFAULT_MIN_TTL,
    DEFAULT_PACKET_SIZE,
    DEFAULT_PORT,
    DEFAULT_QUERIES,
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT,
    Protocol,
)
from src.models import Hop, TracerouteResult

_ARP_LINE_RE = re.compile(
    r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})\s",
)


def _prime_arp_cache_from_os() -> None:
    """Populate scapy's ARP cache from the OS ARP table.

    On Windows Wi-Fi adapters, Npcap frequently fails to observe ARP replies,
    so scapy's own resolution returns None and it falls back to broadcast —
    emitting "MAC address to reach destination not found. Using broadcast."
    repeatedly. Pre-seeding the cache from the OS table avoids that path.
    """
    if platform.system() != "Windows":
        return
    try:
        proc = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return
    for line in proc.stdout.splitlines():
        m = _ARP_LINE_RE.match(line)
        if not m:
            continue
        ip, mac = m.group(1), m.group(2).replace("-", ":").lower()
        scapy_conf.netcache.arp_cache[ip] = mac  # type: ignore[attr-defined]


@dataclass
class ProbeConfig:
    target: str
    min_ttl: int = DEFAULT_MIN_TTL
    max_ttl: int = DEFAULT_MAX_TTL
    queries: int = DEFAULT_QUERIES
    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT
    wait: float = DEFAULT_WAIT
    packet_size: int = DEFAULT_PACKET_SIZE
    protocols: list[Protocol] = field(default_factory=lambda: list(ALL_PROTOCOLS))
    output_path: Path | None = None
    resolved_ip: str | None = None


def _payload_size(total_size: int) -> int:
    return max(0, total_size - 28)


def _probe_dst(config: ProbeConfig) -> str:
    return config.resolved_ip or config.target


def _build_probe(dst: str, ttl: int, protocol: Protocol, port: int, size: int) -> IP:
    payload_bytes = b"\x00" * _payload_size(size)

    ip_layer = IP(dst=dst, ttl=ttl)

    if protocol == Protocol.UDP:
        return ip_layer / UDP(dport=port) / payload_bytes
    elif protocol == Protocol.TCP:
        return ip_layer / TCP(dport=port, flags="S") / payload_bytes
    else:
        return ip_layer / ICMP(type=8) / payload_bytes


def _is_destination_reached(response: Any, protocol: Protocol, dst: str) -> bool:
    if response is None:
        return False

    if IP not in response:
        return False

    resp_ip = response[IP]

    if protocol == Protocol.UDP:
        if resp_ip.src == dst and ICMP in response:
            return cast(int, response[ICMP].type) in (3, 11)
        return False

    elif protocol == Protocol.TCP:
        if resp_ip.src == dst and TCP in response:
            return True
        if resp_ip.src == dst and ICMP in response:
            return cast(int, response[ICMP].type) == 3
        return False

    else:
        if resp_ip.src == dst and ICMP in response:
            return cast(int, response[ICMP].type) == 0
        return False


def _is_time_exceeded(response: Any) -> bool:
    if response is None or ICMP not in response:
        return False
    return cast(int, response[ICMP].type) == 11


def trace_single_target(config: ProbeConfig) -> TracerouteResult:
    _prime_arp_cache_from_os()
    result = TracerouteResult(target=config.target, resolved_ip=config.resolved_ip)
    dst = _probe_dst(config)
    destination_reached = False

    for ttl in range(config.min_ttl, config.max_ttl + 1):
        if destination_reached:
            break

        for protocol in config.protocols:
            hop = Hop(ttl=ttl, protocol=protocol)
            rtts: list[float | None] = []

            for _ in range(config.queries):
                probe = _build_probe(
                    dst=dst,
                    ttl=ttl,
                    protocol=protocol,
                    port=config.port,
                    size=config.packet_size,
                )

                t_start = time.time()
                scapy_conf.verb = 0
                response = sr1(probe, timeout=config.timeout, verbose=0)
                rtt = (time.time() - t_start) * 1000 if response is not None else None

                if response is not None and IP in response:
                    hop.ip = response[IP].src
                rtts.append(rtt)

                if _is_destination_reached(response, protocol, dst):
                    destination_reached = True

                if config.wait > 0:
                    time.sleep(config.wait)

            hop.rtts = rtts
            result.hops.append(hop)

            if config.output_path is not None:
                result.to_json(config.output_path)

    result.destination_reached = destination_reached
    result.probing_complete = True

    if config.output_path is not None:
        result.to_json(config.output_path)

    return result
