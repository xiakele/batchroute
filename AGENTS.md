# Agent Guide — batchroute

## Commands
- Sync deps with `uv sync` (`uv.lock` is committed; keep it in sync after dependency changes).
- CLI entrypoint is `uv run batchroute ...`.
- Real packet probing needs root on Linux because `scapy` sends raw packets. Use `sudo $(which uv) run batchroute -f <targets-file>` (or `sudo $(which uv) run batchroute <target> …`) for end-to-end prober tests.
- Standalone visualizer: `uv run python -m visualizer.app --results-dir results/`.
- Mock data generator (visualizer stress testing): `uv run python scripts/generate_mock_routes.py [--count 100] [--seed N] [--force]`.
- GeoLite2 DB downloader: `uv run python scripts/download_geolite2.py`. Databases land in `data/GeoLite2-City.mmdb` and `data/GeoLite2-ASN.mmdb` (ignored by `.gitignore`).

## Verification Order
- `uv run ruff check src/ visualizer/ scripts/`
- `uv run ruff format --check src/ visualizer/ scripts/`
- `uv run mypy src/ visualizer/ scripts/`
- Full pre-commit run: `uv run pre-commit run --all-files`
- There are no automated tests beyond lint / typecheck. For behavior checks, use `uv run batchroute --help` or a manual probe with a small targets file.
- Note: pre-commit runs mypy in an isolated venv with `additional_dependencies: [pandas-stubs, dnspython, types-Flask, geoip2]`. If mypy passes locally but fails in pre-commit, missing stubs in the isolated env are the likely cause.
- There are real probe results in `results/`. Use them for visualizer testing without needing root / a network.
- The mock generator writes to `mock_results/` by default.

## Repo Structure
- `src/main.py` — sole CLI entrypoint; wires the whole flow.
- `src/config.py` — constants and the `Protocol` enum (`udp`, `tcp`, `icmp`).
- `src/parser.py` — validates targets as IPs or hostnames; syntactically invalid entries are skipped with a warning.
- `src/resolver.py` — forward DNS (`resolve_hostname`) and reverse DNS (`resolve_single_ip`). Both caches are cleared by `clear_cache()`.
- `src/prober.py` — batched async packet engine. Uses a global `AsyncSniffer` (`_GlobalProbeListener`) plus fire-and-forget `send()` instead of blocking `sr1()`. Each probe gets a unique identifier (UDP/TCP source port or ICMP id+seq) so ICMP error responses can be matched back to the original probe. `ProbeConfig.resolved_ip` is set for domain targets so scapy sends to the IP while `TracerouteResult.target` keeps the original domain name.
- `src/geoip.py` — offline GeoLite2-City + ASN lookup with internal-RFC-1918 detection. Uses `data/GeoLite2-City.mmdb` and `data/GeoLite2-ASN.mmdb`.
- `src/models.py` — `TracerouteResult` and `Hop` carry geo fields (`country_code`, `city`, `region`, `lat`, `lon`, `asn_number`, `asn_org`, `is_internal`) plus `cached` and `resolved_ip`. `resolved_ip` is serialized between `target` and `destination_reached` in JSON.
- `src/output.py` — terminal color helpers and `chown_to_invoking_user()` for sudo-run file ownership fixup.
- `visualizer/app.py` — Dash app polling `results/` every 2 s.
- `visualizer/assets/` — CSS and JS files auto-served by Dash. Any `.js` placed here is loaded in the page automatically.
- `visualizer/styles.py` — design tokens, Plotly layout, and Cytoscape stylesheet.
- `scripts/generate_mock_routes.py` — outputs to `mock_results/` by default.
- `scripts/build_release.py` — wrapper around PyInstaller that also creates `dist/batchroute-release.tar.gz`.

## Mock Generator Guarantees
`scripts/generate_mock_routes.py` is the canonical source for visualizer stress-test data. It guarantees these invariants so the visualizer's aggregation logic behaves the same as with real probe results:
- The last TTL hop uses the **target IP** (for IP targets) or **resolved_ip** (for domain targets).
- No router IP ever repeats at non-consecutive TTLs (no self-loops).
- `is_internal` is set only for true RFC-1918 ranges (`10/8`, `172.16/12`, `192.168/16`); shared TEST-NET IPs are not marked internal.
- All geo/ASN fields (`country_code`, `city`, `region`, `lat`, `lon`, `asn_number`, `asn_org`) are present in every hop dict and at the result top level (all `null` in mocks).
- `avg_rtt` is **not rounded**; it must match the value `Hop.avg_rtt` recomputes from `rtts` so JSON round-trips correctly.

## Data Model Quirks
- `Hop.avg_rtt` and `Hop.loss_rate` are **computed properties**, not stored fields. `Hop.from_dict()` ignores the serialized values and recomputes them from `rtts`. Any change to the mock generator or prober must ensure stored `avg_rtt` matches the recomputed value.
- `resolved_ip` is serialized between `target` and `destination_reached` in JSON **only when non-None**. Real IP-target JSON files do not contain a `resolved_ip` key at all.

## Caching & Output
- Targets with a complete result JSON (`probing_complete=True`) in the output directory are reused without re-probing by default.
- `--force` / `-F` re-probes all targets; it deletes only per-target `.json` files and the `.targets` manifest — never other files in the output directory.
- When `--force` would overwrite files, the CLI prints the absolute results directory and asks for confirmation (auto-skipped if stdin is not a TTY, or if `-y`/`--yes` is passed).
- A `.targets` manifest is written to the output directory on every run so the visualizer knows which JSON files belong to the current target list.
- Both `results/` and `mock_results/` are in `.gitignore`.

## Behavior Quirks
- By default, the CLI launches the Dash server before probing starts, opens `http://localhost:8050`, and then blocks after probing so the UI stays up. Use `--no-viz` for non-interactive runs.
- When run under `sudo`, newly created directories (`results/`, `data/`) and files are `chown`ed to the invoking user via `chown_to_invoking_user()`. Any new code that creates directories during a probe should do the same.
- Output is one JSON file per target under `results/` (named by the original target — domain names for domain targets, IPs for IP targets).
- Forward DNS resolution for target domains happens **before** probing starts; unresolvable domains are warned and skipped in `main.py`.
- Reverse DNS resolution (hop hostnames) happens **after** probing finishes for each target; partial JSON written during probing will not yet contain hostnames.
- Default probing sends UDP, TCP SYN, and ICMP for each TTL step unless `-P` restricts the protocol.
- Use `--no-geo` to skip GeoIP lookup entirely (no `data/` directory access, no download prompt).
- Scapy sends packets via the interface associated with the default route (`0.0.0.0`). Use `--iface <name>` to override, or `--list-interfaces` to see available adapters.
- Batch probing: Probes are sent with `send()` and responses are captured by a global `AsyncSniffer` (`_GlobalProbeListener`) rather than blocking `sr1()`. Each probe carries a unique identifier (UDP/TCP source port or ICMP id+seq) so ICMP errors can be matched back to the original probe.
- Per-TTL protocol completeness: `destination_reached` is only checked at the start of the next TTL iteration, not between protocols within the same TTL. All protocols always get their full query count for the current TTL.
- Concurrency control: `-N` / `--sim-queries` sets the max in-flight probes per target (default 32, matching traceroute `-N`). Backpressure pauses sending until room opens up.
- Timing defaults: `DEFAULT_TIMEOUT = 3.0` s, `DEFAULT_WAIT = 0.005` s. Even when `-z 0` is passed, a 5 ms minimum gap is enforced between consecutive probes to avoid zero-spacing bursts that trigger target-side rate limiting.
- Graceful shutdown: `stop_global_listener()` is called after all targets finish probing to tear down the global sniffer. An `atexit` handler also registers it.

## Visualizer Interactivity
- Protocol checkboxes in the legend filter which protocol paths appear in the graph and charts.
- Click-to-focus: Clicking on a node highlights the routes through that node by dimming unrelated nodes/edges to 12% opacity. Clicking the same node again or clicking the Source node restores the full view. Driven by a `focused-node` `dcc.Store`.
- All Cytoscape elements must include an explicit `"classes": ""` key (even when empty) so Dash properly clears dynamic classes like `dimmed` on unfocus.
- Domain targets display as `"domain.com\n(resolved.ip)"` in the graph. The resolved IP node is merged into the target block, not shown separately.
- Node size scales with sample count, not RTT. Shared routers that appear in more targets are drawn larger.
- Node/edge metrics are aggregated across all targets (mean RTT, mean loss). The details panel shows a "Samples" count.
- Missing hops at the maximum TTL are treated as target hops when `destination_reached=True`, so a protocol that times out at the final step still contributes 100% loss to the target node aggregate.
- Dash-cytoscape gotcha: the `global` prop (used to expose the `cy` instance on `window`) is not supported in the version 1.0.2 Python wrapper. If you need to access the underlying Cytoscape instance from JS, traverse the React fiber from the DOM node or use a standalone JS asset in `visualizer/assets/` instead.

## Typecheck / Packaging Notes
- Python target is `>=3.12`.
- Ruff line length is `100`.
- `mypy` is configured with `explicit_package_bases = true` and `mypy_path = "."`; run it from the repo root to avoid module-path issues.
- `mypy` uses `disallow_untyped_defs = true` — all function signatures need type annotations.
- Dash callback data (e.g. `tapNodeData`) returns `Any`; cast or validate before use to satisfy mypy.
- The wheel package list only includes `src` (no `__init__.py` there — it is an implicit namespace package). The runtime currently imports `visualizer.app` directly from the repo.

## Release Binary Builds
- PyInstaller is used to produce directory-based bundles for Linux, macOS, and Windows.
- Spec file: `batchroute.spec` at the repo root. It forces inclusion of `scapy.layers.all`, platform-specific `scapy.arch.*` modules, and collects data files for `dash`, `dash_cytoscape`, `plotly`, `pandas`, and `dns`. Custom `visualizer/assets/` files are also explicitly bundled.
- Local build: `uv run python scripts/build_release.py` (or `uv run pyinstaller batchroute.spec` directly). Output lands in `dist/batchroute/`; the helper script also creates `dist/batchroute-release.tar.gz`.
- CI builds: Push a tag like `v0.2.0` (or run the workflow manually) to trigger `.github/workflows/release-build.yml`. It builds on `ubuntu-latest`, `macos-latest`, and `windows-latest`, then uploads platform archives as both artifacts and GitHub Release assets.
- Platform caveats:
  - Linux / macOS: The binary still requires root (or `CAP_NET_RAW`) for raw packet transmission; this is an OS restriction, not a packaging bug.
  - Windows: End users must install Npcap (or WinPcap) beforehand; the driver cannot be bundled.
- Smoke-test a fresh build with `./dist/batchroute/batchroute --help` and a quick probe (`--no-viz`) before publishing.
