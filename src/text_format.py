from __future__ import annotations

from src.models import Hop, TracerouteResult


def _format_rtt(value: float | None) -> str:
    if value is None:
        return "*"
    return f"{value:.3f} ms"


def _format_host(hop: Hop) -> str:
    if hop.ip is None:
        return "*"
    if hop.hostname:
        return f"{hop.hostname} ({hop.ip})"
    return hop.ip


def format_traceroute_text(result: TracerouteResult) -> str:
    lines: list[str] = []
    header = f"Traceroute to {result.target}"
    if result.resolved_ip:
        header += f" ({result.resolved_ip})"
    lines.append(header)

    hops_by_ttl: dict[int, list[Hop]] = {}
    for hop in result.hops:
        hops_by_ttl.setdefault(hop.ttl, []).append(hop)

    protocol_order = {"udp": 0, "tcp": 1, "icmp": 2}
    sorted_ttls = sorted(hops_by_ttl)
    for ttl in sorted_ttls:
        group = hops_by_ttl[ttl]
        group.sort(key=lambda h: protocol_order.get(h.protocol.value, 99))
        for i, hop in enumerate(group):
            ttl_str = str(ttl) if i == 0 else ""
            proto_tag = f"[{hop.protocol.value.upper()}]"
            host = _format_host(hop)
            rtt_parts = [_format_rtt(r) for r in hop.rtts]
            rtt_str = "  ".join(rtt_parts)
            lines.append(f"{ttl_str:>3}  {proto_tag:<6} {host}  {rtt_str}")
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()

    if not result.destination_reached:
        lines.append("Destination not reached.")

    return "\n".join(lines) + "\n"
