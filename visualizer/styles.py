from __future__ import annotations

SOURCE_NODE_ID = "__source__"

PROTOCOL_COLORS = {
    "udp": "#6B8CB5",
    "tcp": "#C46B6B",
    "icmp": "#6BAF7B",
}

STATUS_COLORS = {
    "probing": "#E8A849",
    "complete": "#5B9E6F",
}

CYTO_BG = "#F5F5F5"

PLOTLY_LAYOUT = {
    "paper_bgcolor": "#fff",
    "plot_bgcolor": "#FAFAFA",
    "font": {
        "family": '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        "size": 12,
        "color": "#666",
    },
    "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
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
                "width": 36,
                "height": 36,
                "background-color": "#7A7A8E",
                "color": "#fff",
                "text-outline-color": "#5A5A6E",
                "text-outline-width": 1,
                "font-family": '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
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
            },
        },
        {
            "selector": "node.target.complete",
            "style": {
                "background-color": "#C46B6B",
                "shape": "rectangle",
                "width": 60,
                "height": 36,
                "font-weight": "bold",
                "font-size": "10px",
            },
        },
        {
            "selector": "node.target.probing",
            "style": {
                "background-color": STATUS_COLORS["probing"],
                "shape": "rectangle",
                "width": 60,
                "height": 36,
                "font-weight": "bold",
                "font-size": "10px",
                "border-width": 2,
                "border-color": "#D4922E",
                "border-style": "dashed",
            },
        },
        {
            "selector": "edge",
            "style": {
                "curve-style": "bezier",
                "width": 1.5,
                "line-color": "#ccc",
                "target-arrow-shape": "triangle",
                "target-arrow-color": "#ccc",
                "opacity": 0.6,
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
