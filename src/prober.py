from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

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
    protocols: list[Protocol] | None = None
    output_path: Path | None = None

    def __post_init__(self):
        if self.protocols is None:
            self.protocols = list(ALL_PROTOCOLS)


def _payload_size(total_size: int) -> int:
    return max(0, total_size - 28)


def _build_probe(target: str, ttl: int, protocol: Protocol, port: int, size: int) -> IP:
    payload_bytes = b"\x00" * _payload_size(size)

    ip_layer = IP(dst=target, ttl=ttl)

    if protocol == Protocol.UDP:
        return ip_layer / UDP(dport=port) / payload_bytes
    elif protocol == Protocol.TCP:
        return ip_layer / TCP(dport=port, flags="S") / payload_bytes
    else:
        return ip_layer / ICMP(type=8) / payload_bytes


def _is_destination_reached(response, protocol: Protocol, target: str) -> bool:
    if response is None:
        return False

    if IP not in response:
        return False

    resp_ip = response[IP]

    if protocol == Protocol.UDP:
        if resp_ip.src == target and ICMP in response:
            return response[ICMP].type in (3, 11)
        return False

    elif protocol == Protocol.TCP:
        if resp_ip.src == target and TCP in response:
            return True
        if resp_ip.src == target and ICMP in response:
            return response[ICMP].type == 3
        return False

    else:
        if resp_ip.src == target and ICMP in response:
            return response[ICMP].type == 0
        return False


def _is_time_exceeded(response) -> bool:
    if response is None or ICMP not in response:
        return False
    return response[ICMP].type == 11


def trace_single_target(config: ProbeConfig) -> TracerouteResult:
    result = TracerouteResult(target=config.target)
    destination_reached = False

    for ttl in range(config.min_ttl, config.max_ttl + 1):
        if destination_reached:
            break

        for protocol in config.protocols:
            hop = Hop(ttl=ttl, protocol=protocol)
            rtts: list[float | None] = []

            for _ in range(config.queries):
                probe = _build_probe(
                    target=config.target,
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

                if _is_destination_reached(response, protocol, config.target):
                    destination_reached = True

                if config.wait > 0:
                    time.sleep(config.wait)

            hop.rtts = rtts
            result.hops.append(hop)

            if config.output_path is not None:
                result.to_json(config.output_path)

    result.destination_reached = destination_reached

    if config.output_path is not None:
        result.to_json(config.output_path)

    return result
