# batchroute

**batchroute** is a batch traceroute tool with an interactive topology visualizer. It probes multiple targets in parallel, writes per-target JSON results, and launches a Dash-based web UI to explore routes, RTTs, and packet loss.

## Repository Layout

```
.
├── src/                    # Core probing engine
│   ├── main.py             # CLI entrypoint
│   ├── config.py           # Protocol enum & defaults
│   ├── parser.py           # Target validation & file parsing
│   ├── resolver.py         # Forward / reverse DNS
│   ├── prober.py           # Async packet engine
│   ├── geoip.py            # GeoLite2 lookups
│   ├── models.py           # TracerouteResult & Hop
│   └── output.py           # Terminal colors & file ownership
├── visualizer/             # Dash application
│   ├── app.py              # Web UI & Cytoscape graph
│   ├── styles.py           # Design tokens & aggregation
│   └── assets/             # Custom CSS / JS
├── scripts/                # Utilities
│   ├── generate_mock_routes.py
│   ├── download_geolite2.py
│   └── build_release.py
├── batchroute.spec         # PyInstaller spec
└── pyproject.toml
```

## Workflow

- **Target ingestion & validation** — Targets come from command-line arguments or a `-f` file (`.txt` or `.csv`). Each entry is validated as an IP address or hostname; syntactically invalid entries are skipped with a warning.

- **Forward DNS** — Domain names are resolved to IPv4/IPv6 addresses before probing starts. Unresolvable domains are warned and excluded from the run.

- **Cache loading** — Existing per-target JSON files in the output directory are checked. Results with `probing_complete=True` are loaded and marked cached; incomplete or missing targets proceed to probing.

- **Batch probing** — For each TTL step, UDP/TCP/ICMP probes are sent asynchronously via a global packet sniffer. Unique identifiers (source ports or ICMP id+seq) match responses back to their original probes.

- **Destination detection** — A target is considered reached on ICMP Echo Reply, TCP SYN-ACK/RST, or ICMP Port Unreachable. Once reached, the program stops probing larger TTLs.

- **GeoIP Lookup** — City, region, and ASN lookups are performed for each responding hop and the target itself. Internal addresses (10.0.0.0/8, 192.168.0.0/16...) are excluded from the lookup.

- **Partial writes** — After every response or timeout, the current hop list is serialized to JSON. This allows the visualizer to show probing progress in real time.

- **Reverse DNS** — After probing completes, hop IP addresses are resolved to hostnames in bulk. Final results are written to the per-target JSON file.

## Visualizer Data Flow

The Dash application polls the `results/` directory every 2 seconds. It reads the `.targets` manifest to know which JSON files belong to the current run, then builds a Cytoscape graph from all matching `TracerouteResult` objects. Nodes and edges are aggregated across protocols to show mean RTT, mean loss rate, and sample counts. Protocol checkboxes filter which paths are rendered, and clicking a target node highlights its path while dimming unrelated routes.

## Key Design Decisions

- **Concurrent Probing** — A single `AsyncSniffer` captures all responses from various TTLs instead of blocking per-probe calls, enabling high concurrency.
- **Per-target JSON caching** — Each target gets its own JSON file. Complete results are reused across runs unless `-F`/`--force` is passed.
- **GeoIP during probing, reverse DNS after** — Hops are enriched with location data as responses arrive, but hostname lookups happen once after the target finishes. This is because GeoIP lookup is fast with the local database, but reverse DNS may block the whole process due to its slow speed.
