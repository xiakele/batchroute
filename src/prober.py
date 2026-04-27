from __future__ import annotations

import ipaddress
import itertools
import platform
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from scapy.config import conf as scapy_conf
from scapy.layers.inet import ICMP, IP, TCP, UDP, ICMPerror, IPerror, TCPerror, UDPerror
from scapy.sendrecv import AsyncSniffer, send

from src.config import (
    ALL_PROTOCOLS,
    DEFAULT_MAX_INFLIGHT,
    DEFAULT_MAX_TTL,
    DEFAULT_MIN_TTL,
    DEFAULT_PACKET_SIZE,
    DEFAULT_PORT,
    DEFAULT_QUERIES,
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT,
    Protocol,
)
from src.geoip import lookup_asn, lookup_ip
from src.models import Hop, TracerouteResult
from src.output import chown_to_invoking_user

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
    max_inflight: int = DEFAULT_MAX_INFLIGHT
    protocols: list[Protocol] = field(default_factory=lambda: list(ALL_PROTOCOLS))
    output_path: Path | None = None
    resolved_ip: str | None = None
    geo: bool = True


@dataclass(frozen=True)
class ProbeKey:
    dst_ip: str
    protocol: Protocol
    ttl: int
    query_index: int
    src_port: int | None = None
    dst_port: int | None = None
    icmp_id: int | None = None
    icmp_seq: int | None = None


@dataclass
class ProbeRecord:
    key: ProbeKey
    sent_ts: float
    timeout_s: float
    event_queue: queue.Queue[ProbeEvent]

    @property
    def deadline_ts(self) -> float:
        return self.sent_ts + self.timeout_s


@dataclass
class ProbeEvent:
    key: ProbeKey
    responder_ip: str | None
    rtt_ms: float | None
    response: Any | None
    timed_out: bool = False


@dataclass
class _HopAccumulator:
    hop: Hop
    rtts: list[float | None]


_PORT_MIN = 20000
_PORT_MAX = 65535
_port_counter = itertools.count(_PORT_MIN)
_port_lock = threading.Lock()

_icmp_seq_counter = itertools.count(1)
_icmp_id_counter = itertools.count(1)
_icmp_counter_lock = threading.Lock()


def _next_src_port() -> int:
    global _port_counter
    with _port_lock:
        value = next(_port_counter)
        if value > _PORT_MAX:
            value = _PORT_MIN
            _port_counter = itertools.count(_PORT_MIN + 1)
        return value


def _next_icmp_identifiers() -> tuple[int, int]:
    with _icmp_counter_lock:
        ident = next(_icmp_id_counter) & 0xFFFF
        seq = next(_icmp_seq_counter) & 0xFFFF
    return ident, seq


class _GlobalProbeListener:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sniffer: AsyncSniffer | None = None
        self._inflight: dict[ProbeKey, ProbeRecord] = {}
        self._udp_index: dict[tuple[str, int, int], ProbeKey] = {}
        self._tcp_index: dict[tuple[str, int, int], ProbeKey] = {}
        self._icmp_index: dict[tuple[str, int, int], ProbeKey] = {}

    def ensure_started(self) -> None:
        with self._lock:
            if self._sniffer is not None:
                return
            self._sniffer = AsyncSniffer(
                store=False,
                filter="icmp or tcp",
                prn=self._handle_packet,
            )
            self._sniffer.start()

    def register(self, record: ProbeRecord) -> None:
        with self._lock:
            self._inflight[record.key] = record
            key = record.key
            if key.protocol == Protocol.UDP:
                assert key.src_port is not None and key.dst_port is not None
                self._udp_index[(key.dst_ip, key.src_port, key.dst_port)] = key
            elif key.protocol == Protocol.TCP:
                assert key.src_port is not None and key.dst_port is not None
                self._tcp_index[(key.dst_ip, key.src_port, key.dst_port)] = key
            else:
                assert key.icmp_id is not None and key.icmp_seq is not None
                self._icmp_index[(key.dst_ip, key.icmp_id, key.icmp_seq)] = key

    def unregister(self, key: ProbeKey) -> ProbeRecord | None:
        with self._lock:
            record = self._inflight.pop(key, None)
            if record is None:
                return None
            self._remove_index_for_key(key)
            return record

    def _remove_index_for_key(self, key: ProbeKey) -> None:
        if key.protocol == Protocol.UDP:
            assert key.src_port is not None and key.dst_port is not None
            self._udp_index.pop((key.dst_ip, key.src_port, key.dst_port), None)
        elif key.protocol == Protocol.TCP:
            assert key.src_port is not None and key.dst_port is not None
            self._tcp_index.pop((key.dst_ip, key.src_port, key.dst_port), None)
        else:
            assert key.icmp_id is not None and key.icmp_seq is not None
            self._icmp_index.pop((key.dst_ip, key.icmp_id, key.icmp_seq), None)

    def _handle_packet(self, packet: Any) -> None:
        matched_key, responder_ip = self._match_key(packet)
        if matched_key is None:
            return

        with self._lock:
            record = self._inflight.pop(matched_key, None)
            if record is None:
                return
            self._remove_index_for_key(matched_key)

        rtt_ms = (time.time() - record.sent_ts) * 1000
        record.event_queue.put(
            ProbeEvent(
                key=record.key,
                responder_ip=responder_ip,
                rtt_ms=rtt_ms,
                response=packet,
                timed_out=False,
            )
        )

    def _match_key(self, packet: Any) -> tuple[ProbeKey | None, str | None]:
        if packet is None or IP not in packet:
            return None, None

        if TCP in packet:
            dst_ip = cast(str, packet[IP].src)
            src_port = cast(int, packet[TCP].dport)
            dst_port = cast(int, packet[TCP].sport)
            with self._lock:
                return self._tcp_index.get((dst_ip, src_port, dst_port)), dst_ip

        if ICMP not in packet:
            return None, None

        icmp_layer = packet[ICMP]
        icmp_type = cast(int, icmp_layer.type)
        responder_ip = cast(str, packet[IP].src)

        if icmp_type == 0:
            ident = cast(int, icmp_layer.id)
            seq = cast(int, icmp_layer.seq)
            with self._lock:
                return self._icmp_index.get((responder_ip, ident, seq)), responder_ip

        if icmp_type not in (3, 11):
            return None, responder_ip

        # ICMP error packets quote the original probe. In Scapy this is often
        # decoded as IPerror/UDPerror/TCPerror/ICMPerror layers, not plain IP/UDP/TCP.
        inner_ip = cast(Any, packet.getlayer(IPerror))
        if inner_ip is None:
            # Fallback to second IP layer if available.
            inner_ip = cast(Any, packet.getlayer(IP, 2))
        if inner_ip is None:
            return None, responder_ip
        dst_ip = cast(str, inner_ip.dst)

        udp_layer = cast(Any, packet.getlayer(UDPerror))
        if udp_layer is None and UDP in inner_ip:
            udp_layer = inner_ip[UDP]
        if udp_layer is not None:
            src_port = cast(int, udp_layer.sport)
            dst_port = cast(int, udp_layer.dport)
            with self._lock:
                return self._udp_index.get((dst_ip, src_port, dst_port)), responder_ip

        tcp_layer = cast(Any, packet.getlayer(TCPerror))
        if tcp_layer is None and TCP in inner_ip:
            tcp_layer = inner_ip[TCP]
        if tcp_layer is not None:
            src_port = cast(int, tcp_layer.sport)
            dst_port = cast(int, tcp_layer.dport)
            with self._lock:
                return self._tcp_index.get((dst_ip, src_port, dst_port)), responder_ip

        icmp_err_layer = cast(Any, packet.getlayer(ICMPerror))
        if icmp_err_layer is None and ICMP in inner_ip:
            icmp_err_layer = inner_ip[ICMP]
        if icmp_err_layer is not None:
            ident = cast(int, icmp_err_layer.id)
            seq = cast(int, icmp_err_layer.seq)
            with self._lock:
                return self._icmp_index.get((dst_ip, ident, seq)), responder_ip

        return None, responder_ip


_global_listener: _GlobalProbeListener | None = None
_global_listener_lock = threading.Lock()


def _get_global_listener() -> _GlobalProbeListener:
    global _global_listener
    with _global_listener_lock:
        if _global_listener is None:
            _global_listener = _GlobalProbeListener()
        _global_listener.ensure_started()
        return _global_listener


def _payload_size(total_size: int) -> int:
    return max(0, total_size - 28)


def _probe_dst(config: ProbeConfig) -> str:
    return config.resolved_ip or config.target


def _build_probe(
    dst: str, ttl: int, protocol: Protocol, port: int, size: int, query_index: int
) -> tuple[IP, ProbeKey]:
    payload_bytes = b"\x00" * _payload_size(size)

    ip_layer = IP(dst=dst, ttl=ttl)

    if protocol == Protocol.UDP:
        src_port = _next_src_port()
        probe = ip_layer / UDP(sport=src_port, dport=port) / payload_bytes
        key = ProbeKey(
            dst_ip=dst,
            protocol=protocol,
            ttl=ttl,
            query_index=query_index,
            src_port=src_port,
            dst_port=port,
        )
        return probe, key
    elif protocol == Protocol.TCP:
        src_port = _next_src_port()
        probe = ip_layer / TCP(sport=src_port, dport=port, flags="S") / payload_bytes
        key = ProbeKey(
            dst_ip=dst,
            protocol=protocol,
            ttl=ttl,
            query_index=query_index,
            src_port=src_port,
            dst_port=port,
        )
        return probe, key
    else:
        ident, seq = _next_icmp_identifiers()
        probe = ip_layer / ICMP(type=8, id=ident, seq=seq) / payload_bytes
        key = ProbeKey(
            dst_ip=dst,
            protocol=protocol,
            ttl=ttl,
            query_index=query_index,
            icmp_id=ident,
            icmp_seq=seq,
        )
        return probe, key


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


def _materialize_hops(
    accumulators: dict[tuple[int, Protocol], _HopAccumulator],
    protocols: list[Protocol],
) -> list[Hop]:
    protocol_order = {protocol: i for i, protocol in enumerate(protocols)}
    ordered = sorted(
        accumulators.items(),
        key=lambda item: (item[0][0], protocol_order[item[0][1]]),
    )
    hops: list[Hop] = []
    for _, acc in ordered:
        acc.hop.rtts = list(acc.rtts)
        hops.append(acc.hop)
    return hops


def _apply_geo_to_hop(hop: Hop) -> None:
    if not hop.ip:
        return
    geo = lookup_ip(hop.ip)
    if geo:
        hop.country_code = geo.country_code
        hop.city = geo.city
        hop.region = geo.region
        hop.lat = geo.lat
        hop.lon = geo.lon
        hop.is_internal = geo.is_internal
    asn = lookup_asn(hop.ip)
    if asn:
        hop.asn_number = asn.asn_number
        hop.asn_org = asn.asn_org


def _apply_geo_to_target(result: TracerouteResult, target_geo_ip: str) -> None:
    try:
        ipaddress.ip_address(target_geo_ip)
        geo = lookup_ip(target_geo_ip)
        if geo:
            result.country_code = geo.country_code
            result.city = geo.city
            result.region = geo.region
            result.lat = geo.lat
            result.lon = geo.lon
            result.is_internal = geo.is_internal
        asn = lookup_asn(target_geo_ip)
        if asn:
            result.asn_number = asn.asn_number
            result.asn_org = asn.asn_org
    except ValueError:
        pass


def _write_partial_result(
    result: TracerouteResult,
    output_path: Path | None,
) -> None:
    if output_path is None:
        return
    result.to_json(output_path)
    chown_to_invoking_user(output_path)


def trace_single_target(config: ProbeConfig) -> TracerouteResult:
    _prime_arp_cache_from_os()
    result = TracerouteResult(target=config.target, resolved_ip=config.resolved_ip)
    dst = _probe_dst(config)
    destination_reached = False
    reached_ttl: int | None = None

    listener = _get_global_listener()
    events: queue.Queue[ProbeEvent] = queue.Queue()
    in_flight: dict[ProbeKey, float] = {}
    accumulators: dict[tuple[int, Protocol], _HopAccumulator] = {}

    max_inflight = max(1, config.max_inflight)
    if config.geo:
        target_geo_ip = config.resolved_ip or config.target
        if target_geo_ip:
            _apply_geo_to_target(result, target_geo_ip)

    def _ensure_accumulator(ttl: int, protocol: Protocol) -> _HopAccumulator:
        key = (ttl, protocol)
        if key not in accumulators:
            accumulators[key] = _HopAccumulator(
                hop=Hop(ttl=ttl, protocol=protocol),
                rtts=[None] * config.queries,
            )
        return accumulators[key]

    def _prune_after_reached_ttl() -> None:
        if reached_ttl is None:
            return
        stale_keys = [k for k in in_flight if k.ttl > reached_ttl]
        for key in stale_keys:
            listener.unregister(key)
            in_flight.pop(key, None)

        stale_accumulators = [acc_key for acc_key in accumulators if acc_key[0] > reached_ttl]
        for acc_key in stale_accumulators:
            accumulators.pop(acc_key, None)

    def _apply_event(event: ProbeEvent) -> None:
        nonlocal destination_reached, reached_ttl
        if reached_ttl is not None and event.key.ttl > reached_ttl:
            return
        acc = _ensure_accumulator(event.key.ttl, event.key.protocol)
        if 0 <= event.key.query_index < len(acc.rtts):
            acc.rtts[event.key.query_index] = event.rtt_ms
        if event.responder_ip is not None:
            acc.hop.ip = event.responder_ip
            if config.geo:
                _apply_geo_to_hop(acc.hop)
        if not event.timed_out and _is_destination_reached(event.response, event.key.protocol, dst):
            destination_reached = True
            if reached_ttl is None:
                reached_ttl = event.key.ttl
            _prune_after_reached_ttl()

    def _drain_events(block_timeout: float = 0.0) -> bool:
        got_event = False
        try:
            if block_timeout > 0:
                event = events.get(timeout=block_timeout)
            else:
                event = events.get_nowait()
            got_event = True
        except queue.Empty:
            return False

        record_deadline = in_flight.pop(event.key, None)
        if record_deadline is not None:
            _apply_event(event)
            result.hops = _materialize_hops(accumulators, config.protocols)
            result.destination_reached = destination_reached
            _write_partial_result(result, config.output_path)

        while True:
            try:
                event = events.get_nowait()
            except queue.Empty:
                break
            record_deadline = in_flight.pop(event.key, None)
            if record_deadline is None:
                continue
            _apply_event(event)
            result.hops = _materialize_hops(accumulators, config.protocols)
            result.destination_reached = destination_reached
            _write_partial_result(result, config.output_path)

        return got_event

    def _expire_timeouts() -> None:
        now = time.time()
        expired = [key for key, deadline in in_flight.items() if deadline <= now]
        for key in expired:
            record = listener.unregister(key)
            in_flight.pop(key, None)
            if record is None:
                continue
            _apply_event(
                ProbeEvent(
                    key=key,
                    responder_ip=None,
                    rtt_ms=None,
                    response=None,
                    timed_out=True,
                )
            )
            result.hops = _materialize_hops(accumulators, config.protocols)
            result.destination_reached = destination_reached
            _write_partial_result(result, config.output_path)

    for ttl in range(config.min_ttl, config.max_ttl + 1):
        if destination_reached:
            break

        for protocol in config.protocols:
            if destination_reached:
                break
            _ensure_accumulator(ttl, protocol)
            for query_index in range(config.queries):
                _drain_events(block_timeout=0.0)
                _expire_timeouts()
                if destination_reached:
                    break

                while len(in_flight) >= max_inflight and not destination_reached:
                    if not _drain_events(block_timeout=0.02):
                        _expire_timeouts()
                if destination_reached:
                    break

                probe, key = _build_probe(
                    dst=dst,
                    ttl=ttl,
                    protocol=protocol,
                    port=config.port,
                    size=config.packet_size,
                    query_index=query_index,
                )

                record = ProbeRecord(
                    key=key,
                    sent_ts=time.time(),
                    timeout_s=config.timeout,
                    event_queue=events,
                )
                listener.register(record)
                in_flight[key] = record.deadline_ts

                scapy_conf.verb = 0
                send(probe, verbose=0)

                _drain_events(block_timeout=0.0)
                _expire_timeouts()
                if destination_reached:
                    break

                if config.wait > 0:
                    time.sleep(config.wait)

    while in_flight:
        next_deadline = min(in_flight.values())
        wait_s = max(0.0, min(0.05, next_deadline - time.time()))
        if not _drain_events(block_timeout=wait_s):
            _expire_timeouts()

    result.hops = _materialize_hops(accumulators, config.protocols)

    result.destination_reached = destination_reached
    result.probing_complete = True

    _write_partial_result(result, config.output_path)
    return result
