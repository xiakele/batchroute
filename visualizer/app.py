from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dash import Dash, dcc, html
from dash.dependencies import Input, Output
import dash_cytoscape as cyto
import plotly.graph_objects as go

from src.models import TracerouteResult

cyto.load_extra_layouts()

SOURCE_NODE_ID = "__source__"

PROTOCOL_COLORS = {
    "udp": "#4C78A8",
    "tcp": "#E45756",
    "icmp": "#54A24B",
}

POLL_INTERVAL_MS = 2000


def _load_results(results_dir: str) -> list[TracerouteResult]:
    results = []
    path = Path(results_dir)
    if not path.exists():
        return results
    for f in sorted(path.glob("*.json")):
        try:
            results.append(TracerouteResult.from_json(f))
        except Exception:
            continue
    return results


def _build_graph_elements(results: list[TracerouteResult]) -> list[dict]:
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    nodes[SOURCE_NODE_ID] = {
        "data": {"id": SOURCE_NODE_ID, "label": "Source"},
    }

    for result in results:
        target_id = result.target
        if target_id not in nodes:
            nodes[target_id] = {
                "data": {
                    "id": target_id,
                    "label": _node_label(result.target, None),
                    "is_target": True,
                },
            }

        by_protocol: dict[str, list] = {}
        for hop in result.hops:
            by_protocol.setdefault(hop.protocol.value, []).append(hop)

        for proto_name, hops in by_protocol.items():
            prev_id = SOURCE_NODE_ID
            for hop in hops:
                if hop.ip is None:
                    node_id = f"*_{result.target}_{hop.ttl}_{proto_name}"
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "data": {
                                "id": node_id,
                                "label": "*",
                                "rtt": None,
                                "loss_rate": 1.0,
                            },
                        }
                else:
                    node_id = hop.ip
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "data": {
                                "id": node_id,
                                "label": _node_label(hop.ip, hop.hostname),
                                "hostname": hop.hostname,
                                "rtt": hop.avg_rtt,
                                "loss_rate": hop.loss_rate,
                            },
                        }

                edge_id = f"{prev_id}_{node_id}_{proto_name}"
                if edge_id not in edges:
                    avg_rtt = hop.avg_rtt
                    loss = hop.loss_rate
                    edges[edge_id] = {
                        "data": {
                            "id": edge_id,
                            "source": prev_id,
                            "target": node_id,
                            "protocol": proto_name,
                            "avg_rtt": avg_rtt,
                            "loss_rate": loss,
                            "weight": max(1, int((avg_rtt or 1))),
                        },
                    }

                prev_id = node_id

            if prev_id != target_id:
                edge_id = f"{prev_id}_{target_id}_{proto_name}"
                if edge_id not in edges:
                    edges[edge_id] = {
                        "data": {
                            "id": edge_id,
                            "source": prev_id,
                            "target": target_id,
                            "protocol": proto_name,
                            "avg_rtt": None,
                            "loss_rate": 0.0,
                            "weight": 1,
                        },
                    }

    return list(nodes.values()) + list(edges.values())


def _node_label(ip: str, hostname: str | None) -> str:
    if hostname:
        return f"{hostname}\n({ip})"
    return ip


def _build_rtt_chart(results: list[TracerouteResult]) -> go.Figure:
    fig = go.Figure()
    for result in results:
        by_protocol: dict[str, list] = {}
        for hop in result.hops:
            by_protocol.setdefault(hop.protocol.value, []).append(hop)

        for proto_name, hops in by_protocol.items():
            ttls = [h.ttl for h in hops]
            avg_rtts = [h.avg_rtt for h in hops]
            fig.add_trace(
                go.Scatter(
                    x=ttls,
                    y=avg_rtts,
                    mode="lines+markers",
                    name=f"{result.target} ({proto_name})",
                    line=dict(color=PROTOCOL_COLORS.get(proto_name, "#999")),
                    connectgaps=True,
                )
            )

    fig.update_layout(
        title="RTT per Hop",
        xaxis_title="TTL",
        yaxis_title="RTT (ms)",
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
    )
    return fig


def _build_loss_chart(results: list[TracerouteResult]) -> go.Figure:
    fig = go.Figure()
    for result in results:
        by_protocol: dict[str, list] = {}
        for hop in result.hops:
            by_protocol.setdefault(hop.protocol.value, []).append(hop)

        for proto_name, hops in by_protocol.items():
            ttls = [h.ttl for h in hops]
            losses = [h.loss_rate * 100 for h in hops]
            fig.add_trace(
                go.Bar(
                    x=ttls,
                    y=losses,
                    name=f"{result.target} ({proto_name})",
                    marker_color=PROTOCOL_COLORS.get(proto_name, "#999"),
                )
            )

    fig.update_layout(
        title="Loss Rate per Hop",
        xaxis_title="TTL",
        yaxis_title="Loss Rate (%)",
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        barmode="group",
    )
    return fig


def create_app(results_dir: str = "results") -> Dash:
    app = Dash(__name__, suppress_callback_exceptions=True)

    app.layout = html.Div(
        [
            html.H1(
                "Batchroute — Topology Visualizer",
                style={"textAlign": "center", "marginBottom": 20},
            ),
            html.Div(
                id="stats-bar",
                style={"textAlign": "center", "marginBottom": 10, "color": "#666"},
            ),
            cyto.Cytoscape(
                id="topo-graph",
                elements=[],
                layout={
                    "name": "breadthfirst",
                    "roots": f"#{SOURCE_NODE_ID}",
                    "directed": True,
                    "spacingFactor": 1.2,
                },
                style={
                    "width": "100%",
                    "height": "600px",
                    "border": "1px solid #ccc",
                    "borderRadius": "4px",
                },
                stylesheet=_cytoscape_stylesheet(),
            ),
            html.Div(
                [
                    html.H3("Node Details", style={"marginTop": 20}),
                    html.Pre(
                        id="node-details",
                        style={
                            "backgroundColor": "#f5f5f5",
                            "padding": 10,
                            "borderRadius": 4,
                        },
                    ),
                ]
            ),
            html.Div(
                [
                    dcc.Graph(id="rtt-chart"),
                    dcc.Graph(id="loss-chart"),
                ],
                style={"marginTop": 20},
            ),
            dcc.Interval(
                id="poll-interval",
                interval=POLL_INTERVAL_MS,
                n_intervals=0,
            ),
            html.Div(
                id="results-dir-store", style={"display": "none"}, children=results_dir
            ),
        ]
    )

    @app.callback(
        [
            Output("topo-graph", "elements"),
            Output("stats-bar", "children"),
            Output("rtt-chart", "figure"),
            Output("loss-chart", "figure"),
        ],
        Input("poll-interval", "n_intervals"),
    )
    def update_graph(_n):
        results = _load_results(results_dir)
        elements = _build_graph_elements(results)
        stats = f"{len(results)} target(s) probed — {len([e for e in elements if 'source' not in e.get('data', {})])} node(s), {len([e for e in elements if 'source' in e.get('data', {})])} edge(s)"
        rtt_fig = _build_rtt_chart(results)
        loss_fig = _build_loss_chart(results)
        return elements, stats, rtt_fig, loss_fig

    @app.callback(
        Output("node-details", "children"),
        Input("topo-graph", "tapNodeData"),
    )
    def show_node_details(data):
        if data is None:
            return "Click a node to see details."
        lines = [f"ID: {data.get('id', '?')}"]
        if data.get("hostname"):
            lines.append(f"Hostname: {data['hostname']}")
        if data.get("rtt") is not None:
            lines.append(f"Avg RTT: {data['rtt']:.2f} ms")
        if data.get("loss_rate") is not None:
            lines.append(f"Loss Rate: {data['loss_rate'] * 100:.1f}%")
        if data.get("is_target"):
            lines.append("Type: Destination")
        return "\n".join(lines)

    return app


def _cytoscape_stylesheet() -> list[dict]:
    return [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "text-wrap": "wrap",
                "text-valign": "center",
                "text-halign": "center",
                "font-size": "10px",
                "width": 40,
                "height": 40,
                "background-color": "#888",
                "color": "#fff",
                "text-outline-color": "#333",
                "text-outline-width": 1,
            },
        },
        {
            "selector": f"node[id = '{SOURCE_NODE_ID}']",
            "style": {
                "background-color": "#222",
                "width": 50,
                "height": 50,
                "font-size": "12px",
                "font-weight": "bold",
            },
        },
        {
            "selector": "node[is_target]",
            "style": {
                "background-color": "#E45756",
                "shape": "rectangle",
                "width": 60,
                "height": 40,
                "font-weight": "bold",
            },
        },
        {
            "selector": "edge",
            "style": {
                "curve-style": "bezier",
                "width": 2,
                "line-color": "#ccc",
                "target-arrow-shape": "triangle",
                "target-arrow-color": "#ccc",
                "opacity": 0.7,
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
    ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batchroute topology visualizer (standalone)."
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Directory containing JSON result files.",
    )
    args = parser.parse_args()
    app = create_app(results_dir=args.results_dir)
    print(f"Launching visualizer at http://localhost:8050 ...")
    app.run(host="0.0.0.0", port=8050, debug=False)
