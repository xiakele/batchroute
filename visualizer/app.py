from __future__ import annotations

import argparse
import logging
from pathlib import Path

import dash_cytoscape as cyto
import plotly.graph_objects as go
from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from src.models import TracerouteResult
from visualizer.styles import (
    CYTO_BG,
    PLOTLY_LAYOUT,
    PROTOCOL_COLORS,
    SOURCE_NODE_ID,
    cytoscape_stylesheet,
)

logging.getLogger("werkzeug").setLevel(logging.ERROR)

cyto.load_extra_layouts()

POLL_INTERVAL_MS = 2000


def _load_results(results_dir: str, targets: set[str] | None = None) -> list[TracerouteResult]:
    results: list[TracerouteResult] = []
    path = Path(results_dir)
    if not path.exists():
        return results
    for f in sorted(path.glob("*.json")):
        if targets is not None and f.stem not in targets:
            continue
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
            max_ttl = max((h.ttl for h in result.hops), default=0)
            current_hops = len(set(h.ttl for h in result.hops))
            label = _node_label(result.target, None)
            if not result.probing_complete and max_ttl > 0:
                label += f"\n({current_hops} hops)"

            if result.cached:
                classes = "target cached"
            elif result.probing_complete:
                classes = "target complete"
            else:
                classes = "target probing"

            nodes[target_id] = {
                "data": {
                    "id": target_id,
                    "label": label,
                    "is_target": True,
                },
                "classes": classes,
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
                            "weight": max(1, int(avg_rtt or 1)),
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


def _build_stats_bar(results: list[TracerouteResult]) -> str:
    if not results:
        return "Waiting for probe data..."
    complete = sum(1 for r in results if r.probing_complete)
    total = len(results)
    return f"{complete} of {total} target(s) complete"


def _build_progress_table(results: list[TracerouteResult]) -> html.Table:
    rows = [
        html.Tr(
            [
                html.Th("Target"),
                html.Th("Hops"),
                html.Th("Status"),
                html.Th("Dest."),
            ]
        )
    ]

    for result in results:
        current_hops = len(set(h.ttl for h in result.hops))

        if result.cached:
            status = html.Span("Cached", className="badge badge-cached")
        elif result.probing_complete:
            status = html.Span("Complete", className="badge badge-complete")
        else:
            status = html.Span("Probing", className="badge badge-probing")

        if result.probing_complete:
            if result.destination_reached:
                dest = html.Span("Reached", className="badge-dest-reached")
            else:
                dest = html.Span("Unreachable", className="badge-dest-unreachable")
        else:
            dest = html.Span("\u2014", className="badge-dest-pending")

        rows.append(
            html.Tr(
                [
                    html.Td(result.target),
                    html.Td(str(current_hops)),
                    html.Td(status),
                    html.Td(dest),
                ]
            )
        )

    return html.Table(rows, className="progress-table")


def _build_legend() -> html.Div:
    items = []
    for proto, color in PROTOCOL_COLORS.items():
        items.append(
            html.Div(
                className="legend-item",
                children=[
                    html.Span(className="legend-dot", style={"backgroundColor": color}),
                    html.Span(proto.upper()),
                ],
            )
        )
    return html.Div(className="legend", children=items)


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
                    line=dict(color=PROTOCOL_COLORS.get(proto_name, "#999"), width=2),
                    marker=dict(size=5),
                    connectgaps=True,
                )
            )

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title="RTT per Hop",
        xaxis_title="TTL",
        yaxis_title="RTT (ms)",
        height=300,
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
        **PLOTLY_LAYOUT,
        title="Loss Rate per Hop",
        xaxis_title="TTL",
        yaxis_title="Loss (%)",
        height=300,
        barmode="group",
    )
    return fig


def create_app(results_dir: str = "results", targets: set[str] | None = None) -> Dash:
    app = Dash(__name__, suppress_callback_exceptions=True, update_title="")
    app.title = "batchroute"

    app.layout = html.Div(
        className="app-container",
        children=[
            html.Header(
                className="header",
                children=[
                    html.H1("batchroute", className="header-title"),
                    html.Div(id="stats-bar", className="header-stats"),
                ],
            ),
            html.Div(
                className="main-grid",
                children=[
                    html.Div(
                        className="graph-card",
                        children=[
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
                                    "backgroundColor": CYTO_BG,
                                },
                                stylesheet=cytoscape_stylesheet(),
                            ),
                        ],
                    ),
                    html.Div(
                        className="sidebar",
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div(
                                        className="card-body",
                                        children=[
                                            html.Div(
                                                className="card-title",
                                                children="Node Details",
                                            ),
                                            html.Pre(
                                                id="node-details",
                                                className="node-details-pre",
                                                children="Click a node to see details.",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div(
                                        className="card-body",
                                        children=[
                                            html.Div(
                                                className="card-title",
                                                children="Probe Progress",
                                            ),
                                            html.Div(id="progress-table"),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div(
                                        className="card-body",
                                        children=[
                                            html.Div(
                                                className="card-title",
                                                children="Protocol",
                                            ),
                                            _build_legend(),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="charts-grid",
                children=[
                    dcc.Graph(id="rtt-chart"),
                    dcc.Graph(id="loss-chart"),
                ],
            ),
            dcc.Interval(
                id="poll-interval",
                interval=POLL_INTERVAL_MS,
                n_intervals=0,
            ),
        ],
    )

    @app.callback(
        [
            Output("topo-graph", "elements"),
            Output("stats-bar", "children"),
            Output("progress-table", "children"),
            Output("rtt-chart", "figure"),
            Output("loss-chart", "figure"),
        ],
        Input("poll-interval", "n_intervals"),
    )
    def update_graph(_n: int) -> tuple:
        results = _load_results(results_dir, targets)
        elements = _build_graph_elements(results)
        stats = _build_stats_bar(results)
        table = _build_progress_table(results)
        rtt_fig = _build_rtt_chart(results)
        loss_fig = _build_loss_chart(results)
        return elements, stats, table, rtt_fig, loss_fig

    @app.callback(
        Output("node-details", "children"),
        Input("topo-graph", "tapNodeData"),
    )
    def show_node_details(data: dict | None) -> str:
        if data is None:
            return "Click a node to see details."
        lines = [f"IP: {data.get('id', '?')}"]
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batchroute topology visualizer (standalone).")
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Directory containing JSON result files.",
    )
    args = parser.parse_args()
    manifest = Path(args.results_dir) / ".targets"
    targets: set[str] | None = None
    if manifest.exists():
        targets = {line.strip() for line in manifest.read_text().splitlines() if line.strip()}
    app = create_app(results_dir=args.results_dir, targets=targets)
    print("Launching visualizer at http://localhost:8050 ...")
    app.run(host="0.0.0.0", port=8050, debug=False)
