# batchroute — Batch Traceroute with Topology Visualization

**batchroute** is a standalone traceroute implementation that probes dozens or hundreds of targets in parallel, writes per-target JSON results, and launches an interactive web-based topology visualizer.

The tool is designed to compare how Internet routing handles different transport protocols. For every TTL step it can send UDP, TCP SYN, and ICMP echo probes (or a subset selected with `-P`), record round-trip times, loss rates, and discovered hop IPs, then render the resulting paths in a browsable graph with RTT and loss charts.

## Quick Start

### From source (with `uv`)

Install dependencies and run the CLI:

```bash
uv sync
uv run batchroute -f targets.txt
```

On Linux, raw packet transmission requires root (or `CAP_NET_RAW`):

```bash
sudo $(which uv) run batchroute -f targets.txt
```

You can also pass targets directly as positional arguments:

```bash
uv run batchroute 1.1.1.1 8.8.8.8 google.com
```

### Pre-built binaries

Compiled binaries for Linux, macOS, and Windows are attached to each [GitHub Release](https://github.com/xiakele/batchroute/releases/latest). Download the archive for your platform, extract it, and run `./batchroute/batchroute` (or `batchroute.exe` on Windows).

> **Platform notes:**
> - **Linux / macOS:** The binary requires root (or `CAP_NET_RAW`) for raw packet transmission.
> - **Windows:** Please install [Npcap](https://npcap.com/) (or WinPcap) beforehand, or have [Wireshark](https://www.wireshark.org/) installed.

Other useful commands:

```bash
# Stand-alone visualizer (point it at an existing results directory)
uv run python -m visualizer.app --results-dir results/

# Mock data generator for stress-testing the UI
uv run python scripts/generate_mock_routes.py --count 100

# Download the GeoLite2 City database for GeoIP lookups
uv run python scripts/download_geolite2.py
```

## Source Code Structure

```
├── src/                          # Core traceroute engine
│   ├── main.py                   # CLI entrypoint; argument parsing, cache logic, worker orchestration
│   ├── config.py                 # Constants and Protocol enum (udp, tcp, icmp)
│   ├── parser.py                 # Target list parser for .txt and .csv input files
│   ├── resolver.py               # Forward DNS (A/AAAA) and reverse DNS (PTR) with in-memory caching
│   ├── prober.py                 # Scapy-based probe construction, transmission, and per-hop result accumulation
│   ├── geoip.py                  # Offline GeoLite2 lookup with internal-RFC-1918 detection
│   ├── models.py                 # Data classes: Hop and TracerouteResult with JSON serialization
│   └── output.py                 # Terminal color helpers and sudo-run file ownership fixup
│
├── visualizer/                   # Dash / Cytoscape web UI
│   ├── app.py                    # Dash application: graph builder, callbacks, charts, detail panel
│   ├── styles.py                 # Design tokens, Cytoscape stylesheet, Plotly layout, and RTT aggregation helpers
│   └── assets/                   # Static files auto-loaded by Dash
│       ├── style.css             # UI layout, card components, progress table styling
│       └── graph_controls.js     # Client-side zoom, center, and fullscreen controls for the topology graph
│
├── scripts/
│   ├── generate_mock_routes.py   # Stand-alone mock-data generator for visualizer stress testing
│   ├── download_geolite2.py      # GeoLite2-City.mmdb downloader
│   └── build_release.py          # PyInstaller wrapper that creates dist/batchroute-release.tar.gz
│
├── batchroute.spec               # PyInstaller spec for Linux, macOS, and Windows bundles
├── pyproject.toml                # Build metadata, dependencies, and tool configuration (ruff, mypy)
└── AGENTS.md                     # Internal developer notes (build commands, behavior quirks)
```

### Module Descriptions

#### `src/main.py`
Wires the entire flow:
1. Parses CLI arguments (`-f`, positional targets, `-m`, `-M`, `-q`, `-p`, `-P`, …).
2. Reads and validates the target list.
3. Resolves domain names to IPs before probing begins.
4. Checks for raw-socket privileges and exits with a clear message if missing.
5. Manages the output directory: loads cached complete results, prompts on `--force` overwrite, and writes a `.targets` manifest so the visualizer knows which JSON files belong to the current run.
6. Offers to download the GeoLite2 database if `--no-geo` was not given and the DB is missing.
7. Spawns a `ThreadPoolExecutor` to probe targets in parallel.
8. Launches the Dash visualizer in a background daemon thread and opens the browser (skipped with `--no-viz`).
9. Blocks after probing so the UI stays alive until the user presses `Ctrl+C`.

#### `src/config.py`
Central location for defaults (TTL bounds, query count, packet size, timeout, output directory) and the `Protocol` enum used throughout the codebase.

#### `src/parser.py`
Accepts `.txt` (one target per line) and `.csv` (first column) files, as well as positional command-line targets. Validates each entry as either a legal IPv4/IPv6 address or a plausible hostname. Invalid entries are warned and skipped.

#### `src/resolver.py`
- `resolve_hostname` queries A then AAAA records via `dnspython`.
- `resolve_single_ip` performs reverse DNS (PTR) lookups.
- Both functions cache results in module-level dictionaries; `clear_cache()` empties them at the end of a run.
- `resolve_result` is called after probing to annotate every hop IP with its hostname.

#### `src/prober.py`
The packet engine:
- `ProbeConfig` bundles all per-target parameters, including `resolved_ip` so domain targets are sent to the IP while keeping the original name in results.
- `_build_probe` crafts an `IP/UDP`, `IP/TCP(SYN)`, or `IP/ICMP` scapy packet sized to the user’s `--size`.
- `trace_single_target` iterates TTL from `min_ttl` to `max_ttl`, sends `queries` probes per protocol, and uses `sr1` to await responses.
- Destination detection is protocol-aware:
  - UDP → ICMP Port Unreachable (type 3) or Time Exceeded (type 11) from the destination IP.
  - TCP → TCP response or ICMP type 3 from the destination IP.
  - ICMP → ICMP Echo Reply (type 0) from the destination IP.
- Partial JSON is written after every hop so the visualizer can show live progress.
- Performs offline GeoIP lookup on each discovered hop when `config.geo` is enabled.

#### `src/geoip.py`
- `lookup_ip` queries `data/GeoLite2-City.mmdb` via `geoip2` and returns country code, latitude, longitude, and an `is_internal` flag for RFC-1918 / loopback addresses.
- `download_geolite2_db` fetches the MMDB from a stable URL if it is missing.
- Results are cached with `@lru_cache`.

#### `src/models.py`
- `Hop` stores TTL, protocol, discovered IP, hostname, per-query RTTs (`None` = timeout), and optional GeoIP fields (`country_code`, `lat`, `lon`, `is_internal`). It exposes `avg_rtt` and `loss_rate` properties.
- `TracerouteResult` stores the target name, hop list, completion flags, optional `resolved_ip`, and optional target-level GeoIP fields. It serializes to compact JSON and can be rehydrated with `from_json`.

#### `src/output.py`
Terminal color helpers (`bold`, `red`, `green`, etc.) plus `chown_to_invoking_user()`, which restores ownership of newly created directories and files to the non-root user when the tool is run under `sudo`.

#### `visualizer/app.py`
Dash application built with `dash-cytoscape` and `plotly`:
- **Topology graph** (`breadthfirst` layout, rooted at a synthetic “Source” node). Nodes represent routers or destinations; edges represent protocol-specific links. Missing hops render as `*` nodes.
- **Protocol filtering** via checkboxes in the legend dynamically rebuilds the graph and charts.
- **Click-to-focus**: selecting a node dims all unrelated nodes and edges to 12 % opacity. Clicking the same target again (or the Source node) restores the full view.
- **Detail panel** shows hop metadata (IP, hostname, TTL, RTT, loss, GeoIP) when a node or edge is clicked.
- **Progress table** lists every target with its current hop count, probing status, and destination-reached state.
- **RTT chart** displays per-TTL median RTT per protocol, with an optional per-target trace overlay.
- **Loss chart** shows mean loss rate per TTL per protocol, again with optional per-target markers.
- A `dcc.Interval` polls the `results/` directory every 2 s so the UI updates while probing is still running.
- Domain targets display as `domain.com\n(resolved.ip)` in the graph; the resolved IP is merged into the target block rather than shown as a separate node.

#### `visualizer/styles.py`
Contains color palettes, Cytoscape CSS selectors (node size mapped to RTT, border color mapped to loss, protocol-colored edges), Plotly layout defaults, and `aggregate_hops_by_protocol` which computes median RTT and mean loss across all targets for the aggregate chart traces.

#### `scripts/generate_mock_routes.py`
A utility that creates fake `TracerouteResult` JSON files. It builds realistic-looking router hostnames, shares a few gateway hops across routes, injects random loss and jitter, and writes the same `.targets` manifest used by the real tool. Useful for testing the visualizer without sending packets on the network.

## Key Design Decisions

- **Protocol comparison by default**: Unless `-P` is given, every TTL step probes UDP, TCP, and ICMP sequentially. This makes path differences between protocols directly visible in the visualizer.
- **Parallelism with caching**: A thread pool probes multiple targets concurrently. Completed results are cached as JSON on disk; re-running with the same output directory skips already-finished targets unless `--force` is used. When `--force` would overwrite files, the CLI asks for confirmation (auto-skipped on non-TTY stdin or with `-y`).
- **Separation of concerns**: DNS resolution happens up-front so scapy sends to an IP, while the result object and JSON keep the original domain name as the target key. Reverse DNS for hops happens after probing so partial files do not block on PTR timeouts.
- **Live visualization**: The Dash server starts before probing and polls the filesystem, so users can watch the graph and charts fill in in real time. Use `--no-viz` for non-interactive runs.
- **Offline GeoIP**: Hop locations are looked up in a local MaxMind GeoLite2 database; no external API calls are made at probe time. Internal / RFC-1918 addresses are flagged automatically.
- **Sudo ownership fixup**: When run under `sudo`, newly created directories and result files are `chown`ed back to the invoking user so permissions remain convenient.
- **Cross-platform probing**: The prober works on Linux, macOS, and Windows. On Windows, end users must install Npcap (or WinPcap) beforehand because the raw-packet driver cannot be bundled.

## Output Format

Each target produces one JSON file named `<target>.json` in the output directory (default `results/`). The schema is:

```json
{
  "target": "example.com",
  "resolved_ip": "93.184.216.34",
  "destination_reached": true,
  "probing_complete": true,
  "cached": false,
  "country_code": "US",
  "lat": 37.751,
  "lon": -97.822,
  "is_internal": false,
  "hops": [
    {
      "ttl": 1,
      "protocol": "udp",
      "ip": "192.168.1.1",
      "hostname": "gateway.home",
      "country_code": null,
      "lat": null,
      "lon": null,
      "is_internal": true,
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
