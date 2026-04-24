# batchroute — Batch Traceroute with Topology Visualization

**batchroute** is a standalone traceroute implementation that probes dozens or hundreds of targets in parallel, writes per-target JSON results, and launches an interactive web-based topology visualizer.

The tool is designed to compare how Internet routing handles different transport protocols. For every TTL step it can send UDP, TCP SYN, and ICMP echo probes (or a subset selected with `-P`), record round-trip times, loss rates, and discovered hop IPs, then render the resulting paths in a browsable graph with RTT and loss charts.

## Source Code Structure

```
├── src/                          # Core traceroute engine
│   ├── main.py                   # CLI entrypoint; argument parsing, cache logic, worker orchestration
│   ├── config.py                 # Constants and Protocol enum (udp, tcp, icmp)
│   ├── parser.py                 # Target list parser for .txt and .csv input files
│   ├── resolver.py               # Forward DNS (A/AAAA) and reverse DNS (PTR) with in-memory caching
│   ├── prober.py                 # Scapy-based probe construction, transmission, and per-hop result accumulation
│   ├── models.py                 # Data classes: Hop and TracerouteResult with JSON serialization
│   └── output.py                 # Terminal color helpers used by the CLI reporter
│
├── visualizer/                   # Dash / Cytoscape web UI
│   ├── app.py                    # Dash application: graph builder, callbacks, charts, detail panel
│   ├── styles.py                 # Design tokens, Cytoscape stylesheet, Plotly layout, and RTT aggregation helpers
│   └── assets/                   # Static files auto-loaded by Dash
│       ├── style.css             # UI layout, card components, progress table styling
│       └── graph_controls.js     # Client-side zoom, center, and fullscreen controls for the topology graph
│
├── scripts/
│   └── generate_mock_routes.py   # Stand-alone mock-data generator for visualizer stress testing
│
├── pyproject.toml                # Build metadata, dependencies, and tool configuration (ruff, mypy)
└── AGENTS.md                     # Internal developer notes (build commands, behavior quirks)
```

### Module Descriptions

#### `src/main.py`
Wires the entire flow:
1. Parses CLI arguments (`-f`, `-m`, `-M`, `-q`, `-p`, `-P`, …).
2. Reads and validates the target list.
3. Resolves domain names to IPs before probing begins.
4. Manages the output directory: loads cached complete results, prompts on `--force` overwrite, and writes a `.targets` manifest so the visualizer knows which JSON files belong to the current run.
5. Spawns a `ThreadPoolExecutor` to probe targets in parallel.
6. Launches the Dash visualizer in a background daemon thread and opens the browser.
7. Blocks after probing so the UI stays alive until the user presses `Ctrl+C`.

#### `src/config.py`
Central location for defaults (TTL bounds, query count, packet size, timeout, output directory) and the `Protocol` enum used throughout the codebase.

#### `src/parser.py`
Accepts `.txt` (one target per line) and `.csv` (first column) files. Validates each entry as either a legal IPv4/IPv6 address or a plausible hostname. Invalid entries are silently skipped.

#### `src/resolver.py`
- `resolve_hostname` queries A then AAAA records via `dnspython`.
- `resolve_single_ip` performs reverse DNS (PTR) lookups.
- Both functions cache results in module-level dictionaries; `clear_cache()` empties them at the end of a run.
- `resolve_result` is called after probing to annotate every hop IP with its hostname.

#### `src/prober.py`
The packet engine:
- `ProbeConfig` bundles all per-target parameters.
- `_build_probe` crafts an `IP/UDP`, `IP/TCP(SYN)`, or `IP/ICMP` scapy packet sized to the user’s `--size`.
- `trace_single_target` iterates TTL from `min_ttl` to `max_ttl`, sends `queries` probes per protocol, and uses `sr1` to await responses.
- Destination detection is protocol-aware:
  - UDP → ICMP Port Unreachable (type 3) or Time Exceeded (type 11) from the destination IP.
  - TCP → TCP response or ICMP type 3 from the destination IP.
  - ICMP → ICMP Echo Reply (type 0) from the destination IP.
- Partial JSON is written after every hop so the visualizer can show live progress.

#### `src/models.py`
- `Hop` stores TTL, protocol, discovered IP, hostname, and a list of per-query RTTs (`None` = timeout). It exposes `avg_rtt` and `loss_rate` properties.
- `TracerouteResult` stores the target name, hop list, completion flags, and optional `resolved_ip`. It serializes to compact JSON and can be rehydrated with `from_json`.

#### `visualizer/app.py`
Dash application built with `dash-cytoscape` and `plotly`:
- **Topology graph** (`breadthfirst` layout, rooted at a synthetic “Source” node). Nodes represent routers or destinations; edges represent protocol-specific links. Missing hops render as `*` nodes.
- **Protocol filtering** via checkboxes in the legend dynamically rebuilds the graph and charts.
- **Click-to-focus**: selecting a node dims all unrelated nodes and edges to 12 % opacity.
- **Detail panel** shows hop metadata (IP, hostname, TTL, RTT, loss) when a node or edge is clicked.
- **Progress table** lists every target with its current hop count, probing status, and destination-reached state.
- **RTT chart** displays per-TTL median RTT per protocol, with an optional per-target trace overlay.
- **Loss chart** shows mean loss rate per TTL per protocol, again with optional per-target markers.
- A `dcc.Interval` polls the `results/` directory every 2 s so the UI updates while probing is still running.

#### `visualizer/styles.py`
Contains color palettes, Cytoscape CSS selectors (node size mapped to RTT, border color mapped to loss, protocol-colored edges), Plotly layout defaults, and `aggregate_hops_by_protocol` which computes median RTT and mean loss across all targets for the aggregate chart traces.

#### `scripts/generate_mock_routes.py`
A utility that creates fake `TracerouteResult` JSON files. It builds realistic-looking router hostnames, shares a few gateway hops across routes, injects random loss and jitter, and writes the same `.targets` manifest used by the real tool. Useful for testing the visualizer without sending packets on the network.

## Key Design Decisions

- **Protocol comparison by default**: Unless `-P` is given, every TTL step probes UDP, TCP, and ICMP sequentially. This makes path differences between protocols directly visible in the visualizer.
- **Parallelism with caching**: A thread pool probes multiple targets concurrently. Completed results are cached as JSON on disk; re-running with the same output directory skips already-finished targets unless `--force` is used.
- **Separation of concerns**: DNS resolution happens up-front so scapy sends to an IP, while the result object and JSON keep the original domain name as the target key. Reverse DNS for hops happens after probing so partial files do not block on PTR timeouts.
- **Live visualization**: The Dash server starts before probing and polls the filesystem, so users can watch the graph and charts fill in in real time.
- **Cross-platform probing**: The prober works on Linux, macOS, and Windows. On Windows it pre-seeds the scapy ARP cache from the OS `arp -a` table to avoid repeated broadcast warnings on Wi-Fi adapters.

## Output Format

Each target produces one JSON file named `<target>.json` in the output directory (default `results/`). The schema is:

```json
{
  "target": "example.com",
  "resolved_ip": "93.184.216.34",
  "destination_reached": true,
  "probing_complete": true,
  "cached": false,
  "hops": [
    {
      "ttl": 1,
      "protocol": "udp",
      "ip": "192.168.1.1",
      "hostname": "gateway.home",
      "rtts": [1.234, 1.198, 1.245],
      "avg_rtt": 1.226,
      "loss_rate": 0.0
    }
  ]
}
```

A `.targets` manifest is also written so the visualizer knows which files belong to the current run.

## License

GPL-2.0-or-later
