from __future__ import annotations

import argparse
import logging
import statistics
from pathlib import Path

import dash_cytoscape as cyto
import flask.cli
import plotly.graph_objects as go
from dash import Dash, dcc, html
from dash.dependencies import Input, Output

from src.models import TracerouteResult
from visualizer.styles import (
    CYTO_BG,
    LOSS_HIGH_COLOR,
    LOSS_LOW_COLOR,
    PLOTLY_LAYOUT,
    PROTOCOL_COLORS,
    SOURCE_NODE_ID,
    aggregate_hops_by_protocol,
    cytoscape_stylesheet,
)

logging.getLogger("werkzeug").setLevel(logging.ERROR)

cyto.load_extra_layouts()

POLL_INTERVAL_MS = 2000
AGGREGATE_DEFAULT_THRESHOLD = 20


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


def _build_graph_elements(
    results: list[TracerouteResult], protocols: set[str] | None = None
) -> list[dict]:
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    if protocols is None:
        protocols = set(PROTOCOL_COLORS.keys())

    nodes[SOURCE_NODE_ID] = {
        "data": {"id": SOURCE_NODE_ID, "label": "Source"},
    }

    for result in results:
        target_id = result.target
        resolved_ip = getattr(result, "resolved_ip", None) or None
        if target_id not in nodes:
            max_ttl = max((h.ttl for h in result.hops), default=0)
            current_hops = len(set(h.ttl for h in result.hops))
            label = _node_label(result.target, resolved_ip)
            if not result.probing_complete and max_ttl > 0:
                label += f"\n({current_hops} hops)"

            if result.cached:
                classes = "target cached"
            elif result.probing_complete:
                classes = "target complete"
            else:
                classes = "target probing"
            if result.probing_complete and not result.destination_reached:
                classes += " unreachable"

            nodes[target_id] = {
                "data": {
                    "id": target_id,
                    "label": label,
                    "is_target": True,
                    "destination_reached": result.destination_reached,
                    "probing_complete": result.probing_complete,
                    "cached": result.cached,
                    "hop_count": current_hops,
                },
                "classes": classes,
            }

        by_protocol: dict[str, list] = {}
        for hop in result.hops:
            by_protocol.setdefault(hop.protocol.value, []).append(hop)

        target_ips: set[str] = set()
        if resolved_ip:
            target_ips.add(resolved_ip)

        for proto_name, hops in by_protocol.items():
            if proto_name not in protocols:
                continue
            prev_id = SOURCE_NODE_ID
            for hop in hops:
                if hop.ip is None:
                    node_id = f"*_{result.target}_{hop.ttl}_{proto_name}"
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "data": {
                                "id": node_id,
                                "label": "*",
                                "rtt": 0,
                                "loss_rate": 1.0,
                                "missing": True,
                                "ttl": hop.ttl,
                            },
                        }
                elif hop.ip in target_ips:
                    node_id = target_id
                else:
                    node_id = hop.ip
                    if node_id not in nodes:
                        nodes[node_id] = {
                            "data": {
                                "id": node_id,
                                "label": _node_label(hop.ip, hop.hostname),
                                "hostname": hop.hostname,
                                "rtt": hop.avg_rtt if hop.avg_rtt is not None else 0,
                                "loss_rate": hop.loss_rate,
                                "ttl": hop.ttl,
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


def _metric_chip(label: str, value: str) -> html.Span:
    return html.Span(
        className="metric-chip",
        children=[
            html.Span(label, className="metric-chip-label"),
            html.Span(value, className="metric-chip-value"),
        ],
    )


def _build_stats_bar(results: list[TracerouteResult]) -> list:
    if not results:
        return [html.Span("Waiting for probe data…", className="details-empty")]

    total = len(results)
    complete = sum(1 for r in results if r.probing_complete)
    reached = sum(1 for r in results if r.probing_complete and r.destination_reached)

    hop_counts = [len({h.ttl for h in r.hops}) for r in results if r.hops]
    avg_hops = f"{statistics.mean(hop_counts):.1f}" if hop_counts else "—"

    all_losses = [h.loss_rate for r in results for h in r.hops]
    overall_loss = f"{statistics.mean(all_losses) * 100:.1f}%" if all_losses else "—"

    return [
        _metric_chip("Targets", f"{complete}/{total}"),
        _metric_chip("Reached", str(reached)),
        _metric_chip("Avg hops", avg_hops),
        _metric_chip("Loss", overall_loss),
    ]


def _build_progress_table(results: list[TracerouteResult]) -> html.Div:
    header = html.Thead(
        html.Tr(
            [
                html.Th("Target"),
                html.Th("Hops"),
                html.Th("Status"),
                html.Th("Dest."),
            ]
        )
    )

    body_rows = []
    for result in results:
        current_hops = len({h.ttl for h in result.hops})

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

        body_rows.append(
            html.Tr(
                [
                    html.Td(result.target, className="target-cell"),
                    html.Td(str(current_hops)),
                    html.Td(status),
                    html.Td(dest),
                ]
            )
        )

    return html.Div(
        className="progress-table-wrap",
        children=html.Table(
            className="progress-table",
            children=[header, html.Tbody(body_rows)],
        ),
    )


def _build_legend() -> html.Div:
    all_protos = list(PROTOCOL_COLORS.keys())

    select_all = dcc.Checklist(
        id="protocol-select-all",
        options=[{"label": " Select All", "value": "all"}],
        value=["all"],
        className="legend-select-all",
    )

    proto_checklist = dcc.Checklist(
        id="protocol-filter",
        options=[
            {
                "label": html.Span(
                    [
                        html.Span(
                            className="legend-dot",
                            style={"backgroundColor": color},
                        ),
                        f" {proto.upper()}",
                    ]
                ),
                "value": proto,
            }
            for proto, color in PROTOCOL_COLORS.items()
        ],
        value=all_protos,
        className="legend-protocols",
    )

    encoding_row = html.Div(
        className="legend-row",
        children=[
            html.Span(
                className="legend-item",
                title="Node size scales with average RTT",
                children=[
                    html.Span(className="legend-size-sm"),
                    html.Span(className="legend-size-lg"),
                    html.Span("RTT"),
                ],
            ),
            html.Span(
                className="legend-item",
                title="Node border / edge color reflects packet loss",
                children=[
                    html.Span(
                        className="legend-bar",
                        style={
                            "background": (
                                f"linear-gradient(to right, {LOSS_LOW_COLOR}, {LOSS_HIGH_COLOR})"
                            )
                        },
                    ),
                    html.Span("Loss"),
                ],
            ),
        ],
    )

    return html.Div(
        className="legend",
        children=[
            html.Div(
                className="legend-protocol-header",
                children=[
                    html.Div("Protocol", className="legend-group-title"),
                    select_all,
                ],
            ),
            proto_checklist,
            html.Div("Encoding", className="legend-group-title"),
            encoding_row,
        ],
    )


def _format_details_list(pairs: list[tuple[str, str]]) -> html.Dl:
    children: list = []
    for k, v in pairs:
        children.append(html.Dt(k))
        children.append(html.Dd(v))
    return html.Dl(className="details-list", children=children)


def _empty_details() -> list:
    return [html.Div("Click a node or edge to see details.", className="details-empty")]


def _node_details(data: dict) -> list:
    if data.get("id") == SOURCE_NODE_ID:
        kind = "Source"
        pairs: list[tuple[str, str]] = [("Role", "Probe origin")]
    elif data.get("is_target"):
        kind = "Destination"
        pairs = [("IP", str(data.get("id", "?")))]
        if data.get("hostname"):
            pairs.append(("Hostname", str(data["hostname"])))
        pairs.append(("Hops", str(data.get("hop_count", "—"))))
        if data.get("cached"):
            status_text = "Cached"
        elif data.get("probing_complete"):
            status_text = "Reached" if data.get("destination_reached") else "Unreachable"
        else:
            status_text = "Probing"
        pairs.append(("Status", status_text))
    elif data.get("missing"):
        kind = "Missing hop"
        pairs = [
            ("TTL", str(data.get("ttl", "—"))),
            ("Response", "Timed out"),
        ]
    else:
        kind = "Router"
        pairs = [("IP", str(data.get("id", "?")))]
        if data.get("hostname"):
            pairs.append(("Hostname", str(data["hostname"])))
        if data.get("ttl") is not None:
            pairs.append(("TTL", str(data["ttl"])))
        rtt = data.get("rtt")
        pairs.append(("Avg RTT", f"{rtt:.2f} ms" if rtt else "—"))
        loss = data.get("loss_rate")
        pairs.append(("Loss", f"{loss * 100:.1f}%" if loss is not None else "—"))

    return [html.Div(kind, className="details-kind"), _format_details_list(pairs)]


def _edge_details(data: dict) -> list:
    avg_rtt = data.get("avg_rtt")
    loss = data.get("loss_rate")
    pairs = [
        ("Protocol", str(data.get("protocol", "?")).upper()),
        ("From", str(data.get("source", "?"))),
        ("To", str(data.get("target", "?"))),
        ("Avg RTT", f"{avg_rtt:.2f} ms" if avg_rtt else "—"),
        ("Loss", f"{loss * 100:.1f}%" if loss is not None else "—"),
    ]
    return [html.Div("Link", className="details-kind"), _format_details_list(pairs)]


def _build_rtt_chart(
    results: list[TracerouteResult], per_target: bool, protocols: set[str] | None = None
) -> go.Figure:
    if protocols is None:
        protocols = set(PROTOCOL_COLORS.keys())

    fig = go.Figure()

    if per_target:
        for result in results:
            by_protocol: dict[str, list] = {}
            for hop in result.hops:
                by_protocol.setdefault(hop.protocol.value, []).append(hop)
            for proto_name, hops in by_protocol.items():
                if proto_name not in protocols:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=[h.ttl for h in hops],
                        y=[h.avg_rtt for h in hops],
                        mode="lines+markers",
                        name=f"{result.target} ({proto_name})",
                        line=dict(
                            color=PROTOCOL_COLORS.get(proto_name, "#999"),
                            width=1.2,
                        ),
                        marker=dict(size=4),
                        opacity=0.4,
                        connectgaps=True,
                        hovertemplate="TTL %{x}<br>%{y:.1f} ms<extra>%{fullData.name}</extra>",
                    )
                )

    agg = aggregate_hops_by_protocol(results)
    for proto_name, series in agg.items():
        if proto_name not in protocols:
            continue
        fig.add_trace(
            go.Scatter(
                x=[s[0] for s in series],
                y=[s[1] for s in series],
                mode="lines+markers",
                name=f"{proto_name.upper()} (median)",
                line=dict(color=PROTOCOL_COLORS.get(proto_name, "#999"), width=2.5),
                marker=dict(size=6),
                connectgaps=True,
                hovertemplate="TTL %{x}<br>%{y:.1f} ms<extra>%{fullData.name}</extra>",
            )
        )

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=dict(text="RTT per Hop", font=dict(size=13)),
        xaxis_title="TTL",
        yaxis_title="RTT (ms)",
    )
    return fig


def _build_loss_chart(
    results: list[TracerouteResult], per_target: bool, protocols: set[str] | None = None
) -> go.Figure:
    if protocols is None:
        protocols = set(PROTOCOL_COLORS.keys())

    fig = go.Figure()

    if per_target:
        for result in results:
            by_protocol: dict[str, list] = {}
            for hop in result.hops:
                by_protocol.setdefault(hop.protocol.value, []).append(hop)
            for proto_name, hops in by_protocol.items():
                if proto_name not in protocols:
                    continue
                fig.add_trace(
                    go.Scatter(
                        x=[h.ttl for h in hops],
                        y=[h.loss_rate * 100 for h in hops],
                        mode="markers",
                        name=f"{result.target} ({proto_name})",
                        marker=dict(
                            color=PROTOCOL_COLORS.get(proto_name, "#999"),
                            size=5,
                            opacity=0.35,
                        ),
                        hovertemplate="TTL %{x}<br>%{y:.1f}%<extra>%{fullData.name}</extra>",
                    )
                )

    agg = aggregate_hops_by_protocol(results)
    for proto_name, series in agg.items():
        if proto_name not in protocols:
            continue
        fig.add_trace(
            go.Bar(
                x=[s[0] for s in series],
                y=[s[2] * 100 for s in series],
                name=f"{proto_name.upper()} (mean)",
                marker_color=PROTOCOL_COLORS.get(proto_name, "#999"),
                opacity=0.85,
                hovertemplate="TTL %{x}<br>%{y:.1f}%<extra>%{fullData.name}</extra>",
            )
        )

    fig.update_layout(
        **PLOTLY_LAYOUT,
        title=dict(text="Loss Rate per Hop", font=dict(size=13)),
        xaxis_title="TTL",
        yaxis_title="Loss (%)",
        barmode="group",
    )
    return fig


def create_app(results_dir: str = "results", targets: set[str] | None = None) -> Dash:
    app = Dash(__name__, suppress_callback_exceptions=True, update_title="")
    app.logger.setLevel(logging.WARNING)
    flask.cli.show_server_banner = lambda *a, **kw: None
    app.title = "batchroute"

    initial_per_target = targets is None or len(targets) <= AGGREGATE_DEFAULT_THRESHOLD

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
                                    "height": "100%",
                                    "backgroundColor": CYTO_BG,
                                },
                                minZoom=0.2,
                                maxZoom=3.0,
                                wheelSensitivity=0.2,
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
                                                children="Details",
                                            ),
                                            html.Div(
                                                id="element-details",
                                                className="details-block",
                                                children=_empty_details(),
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
                                                children="Legend",
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
                className="chart-controls",
                children=[
                    dcc.Checklist(
                        id="per-target-toggle",
                        options=[{"label": " Per-target traces", "value": "on"}],
                        value=["on"] if initial_per_target else [],
                    ),
                ],
            ),
            html.Div(
                className="charts-grid",
                children=[
                    dcc.Graph(
                        id="rtt-chart",
                        style={"height": "var(--chart-h)"},
                        config={"displayModeBar": False},
                    ),
                    dcc.Graph(
                        id="loss-chart",
                        style={"height": "var(--chart-h)"},
                        config={"displayModeBar": False},
                    ),
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
        [
            Input("poll-interval", "n_intervals"),
            Input("per-target-toggle", "value"),
            Input("protocol-filter", "value"),
        ],
    )
    def update_graph(_n: int, per_target_value: list[str], proto_value: list[str]) -> tuple:
        results = _load_results(results_dir, targets)
        per_target = bool(per_target_value)
        protocols = set(proto_value) if proto_value else set()
        return (
            _build_graph_elements(results, protocols),
            _build_stats_bar(results),
            _build_progress_table(results),
            _build_rtt_chart(results, per_target, protocols),
            _build_loss_chart(results, per_target, protocols),
        )

    @app.callback(
        [Output("protocol-select-all", "value"), Output("protocol-filter", "value")],
        [
            Input("protocol-select-all", "value"),
            Input("protocol-filter", "value"),
        ],
    )
    def sync_protocol_checkboxes(
        select_all: list[str] | None, protocols: list[str] | None
    ) -> tuple:
        from dash import callback_context

        all_protos = list(PROTOCOL_COLORS.keys())
        ctx = callback_context

        if not ctx.triggered:
            return ["all"], all_protos

        triggered_id = ctx.triggered[0]["prop_id"]

        if triggered_id == "protocol-select-all.value":
            if select_all and "all" in select_all:
                return ["all"], all_protos
            return [], []

        protocols = protocols or []
        if set(protocols) == set(all_protos):
            return ["all"], protocols
        return [], protocols

    @app.callback(
        Output("element-details", "children"),
        [
            Input("topo-graph", "tapNodeData"),
            Input("topo-graph", "tapEdgeData"),
        ],
    )
    def show_element_details(node: dict | None, edge: dict | None) -> list:
        from dash import callback_context

        trig = callback_context.triggered
        if not trig:
            return _empty_details()
        prop = trig[0].get("prop_id", "")
        if prop.startswith("topo-graph.tapEdgeData") and edge:
            return _edge_details(edge)
        if prop.startswith("topo-graph.tapNodeData") and node:
            return _node_details(node)
        if node is not None:
            return _node_details(node)
        if edge is not None:
            return _edge_details(edge)
        return _empty_details()

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
