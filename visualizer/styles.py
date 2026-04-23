from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import Hop, TracerouteResult

SOURCE_NODE_ID = "__source__"

PROTOCOL_COLORS = {
    "udp": "#6B8CB5",
    "tcp": "#C46B6B",
    "icmp": "#6BAF7B",
}

STATUS_COLORS = {
    "probing": "#C97B00",
    "complete": "#4A8C5E",
    "cached": "#6B7F90",
}

LOSS_LOW_COLOR = "#4A8C5E"
LOSS_HIGH_COLOR = "#B05050"

CYTO_BG = "#F5F5F5"

PLOTLY_LAYOUT = {
    "paper_bgcolor": "#fff",
    "plot_bgcolor": "#FAFAFA",
    "font": {
        "family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        "size": 12,
        "color": "#666",
    },
    "margin": {"l": 50, "r": 20, "t": 50, "b": 40},
    "legend": {
        "orientation": "h",
        "yanchor": "bottom",
        "y": 1.02,
        "xanchor": "right",
        "x": 1.0,
        "font": {"size": 10},
    },
    "xaxis": {
        "gridcolor": "#E8E8E8",
        "linecolor": "#E8E8E8",
        "zerolinecolor": "#E8E8E8",
    },
    "yaxis": {
        "gridcolor": "#E8E8E8",
        "linecolor": "#E8E8E8",
        "zerolinecolor": "#E8E8E8",
    },
}


def cytoscape_stylesheet() -> list[dict]:
    return [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "text-wrap": "wrap",
                "text-valign": "center",
                "text-halign": "center",
                "font-size": "10px",
                "width": 30,
                "height": 30,
                "background-color": "#7A7A8E",
                "color": "#fff",
                "text-outline-color": "#5A5A6E",
                "text-outline-width": 1,
                "font-family": '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
                "border-width": 2,
                "border-opacity": 0.85,
            },
        },
        {
            "selector": "node[rtt]",
            "style": {
                "width": "mapData(rtt, 0, 200, 30, 75)",
                "height": "mapData(rtt, 0, 200, 30, 75)",
            },
        },
        {
            "selector": "node[loss_rate]",
            "style": {
                "border-color": f"mapData(loss_rate, 0, 1, {LOSS_LOW_COLOR}, {LOSS_HIGH_COLOR})",
            },
        },
        {
            "selector": "node[?missing]",
            "style": {
                "width": 26,
                "height": 26,
                "background-color": "#BDBDBD",
                "border-style": "dashed",
                "border-color": LOSS_HIGH_COLOR,
                "color": "#888",
                "text-outline-color": "#EEE",
            },
        },
        {
            "selector": f"node[id = '{SOURCE_NODE_ID}']",
            "style": {
                "background-color": "#3D3D56",
                "width": 48,
                "height": 48,
                "font-size": "11px",
                "font-weight": "bold",
                "border-width": 0,
            },
        },
        {
            "selector": "node.target",
            "style": {
                "shape": "round-rectangle",
                "width": 64,
                "height": 38,
                "font-weight": "bold",
                "font-size": "10px",
                "border-width": 2,
            },
        },
        {
            "selector": "node.target.complete",
            "style": {
                "background-color": STATUS_COLORS["complete"],
                "border-color": STATUS_COLORS["complete"],
            },
        },
        {
            "selector": "node.target.probing",
            "style": {
                "background-color": STATUS_COLORS["probing"],
                "border-color": "#A45E00",
                "border-style": "dashed",
            },
        },
        {
            "selector": "node.target.cached",
            "style": {
                "background-color": STATUS_COLORS["cached"],
                "border-color": STATUS_COLORS["cached"],
            },
        },
        {
            "selector": "node.target.unreachable",
            "style": {
                "background-color": LOSS_HIGH_COLOR,
                "border-color": LOSS_HIGH_COLOR,
                "border-width": 3,
            },
        },
        {
            "selector": "edge",
            "style": {
                "curve-style": "bezier",
                "width": "mapData(weight, 1, 120, 1.2, 6)",
                "line-color": "#ccc",
                "target-arrow-shape": "triangle",
                "target-arrow-color": "#ccc",
                "opacity": 0.65,
            },
        },
        {
            "selector": "edge[loss_rate >= 0.5]",
            "style": {
                "line-style": "dashed",
                "opacity": 0.5,
            },
        },
        {
            "selector": "edge[protocol = 'udp']",
            "style": {
                "line-color": PROTOCOL_COLORS["udp"],
                "target-arrow-color": PROTOCOL_COLORS["udp"],
            },
        },
        {
            "selector": "edge[protocol = 'tcp']",
            "style": {
                "line-color": PROTOCOL_COLORS["tcp"],
                "target-arrow-color": PROTOCOL_COLORS["tcp"],
            },
        },
        {
            "selector": "edge[protocol = 'icmp']",
            "style": {
                "line-color": PROTOCOL_COLORS["icmp"],
                "target-arrow-color": PROTOCOL_COLORS["icmp"],
            },
        },
        {
            "selector": ":selected",
            "style": {
                "border-width": 3,
                "border-color": "#3D3D56",
                "opacity": 1,
            },
        },
        {
            "selector": ".dimmed",
            "style": {
                "opacity": 0.12,
            },
        },
    ]


def aggregate_hops_by_protocol(
    results: list[TracerouteResult],
) -> dict[str, list[tuple[int, float | None, float]]]:
    """Aggregate hops across targets by protocol.

    Returns: {protocol -> [(ttl, median_rtt_ms, mean_loss_rate)]}.
    """
    import statistics

    buckets: dict[str, dict[int, list[Hop]]] = {}
    for result in results:
        for hop in result.hops:
            proto = hop.protocol.value
            buckets.setdefault(proto, {}).setdefault(hop.ttl, []).append(hop)

    out: dict[str, list[tuple[int, float | None, float]]] = {}
    for proto, by_ttl in buckets.items():
        series: list[tuple[int, float | None, float]] = []
        for ttl in sorted(by_ttl):
            hops = by_ttl[ttl]
            rtts = [h.avg_rtt for h in hops if h.avg_rtt is not None]
            median_rtt = statistics.median(rtts) if rtts else None
            mean_loss = sum(h.loss_rate for h in hops) / len(hops)
            series.append((ttl, median_rtt, mean_loss))
        out[proto] = series
    return out
