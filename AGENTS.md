# Agent Guide — batchroute

## Commands
- Sync deps with `uv sync`.
- CLI entrypoint is `uv run batchroute ...`.
- Target files accept both IP addresses and domain names (forward DNS resolution via dnspython).
- Real packet probing needs root on Linux because `scapy` sends raw packets. Use `sudo $(which uv) run batchroute -f <targets-file>` when exercising the prober end-to-end.
- Standalone visualizer: `uv run python -m visualizer.app --results-dir results/`.
- Mock data generator (for visualizer stress testing): `uv run python scripts/generate_mock_routes.py [--count 100] [--seed N] [--force]`.

## Verification Order
- Run `uv run ruff check src/ visualizer/ scripts/`.
- Run `uv run ruff format --check src/ visualizer/ scripts/`.
- Run `uv run mypy src/ visualizer/ scripts/`.
- `pre-commit` is installed and enforces the same checks plus whitespace / EOF fixers on every commit. Full run: `uv run pre-commit run --all-files`.
- There are no automated tests beyond lint / typecheck. For behavior checks, use `uv run batchroute --help` or a manual probe with a small targets file.

## Repo Structure
- `src/main.py` is the only CLI entrypoint and wires the whole flow.
- `src/parser.py` validates target entries — accepts both IPs (`ipaddress.ip_address`) and hostnames (DNS-label regex). Invalid hostnames print a warning and are skipped.
- `src/resolver.py` handles both forward DNS (`resolve_hostname` for target domains) and reverse DNS (`resolve_single_ip` for hop hostnames). Both caches are cleared by `clear_cache()`.
- `src/prober.py` handles probing and writes partial JSON updates during probing, not just a final file. `ProbeConfig.resolved_ip` is set for domain targets so scapy sends packets to the IP while `TracerouteResult.target` retains the original domain name.
- `src/models.py`: `TracerouteResult` has `cached` and `resolved_ip` fields. `resolved_ip` stores the forward-resolved IP for domain targets (absent for IP targets). Serialized between `target` and `destination_reached` in JSON.
- `visualizer/app.py` is a Dash app that polls `results/` every 2 seconds and is designed to show nodes appearing in real time.
- Visualizer styling is split between `visualizer/assets/style.css` (page CSS auto-served by Dash) and `visualizer/styles.py` (design tokens, Plotly layout, Cytoscape stylesheet).
- `scripts/generate_mock_routes.py` generates mock traceroute JSON files for visualizer stress testing. Output defaults to `mock_results/`.

## Caching & Output
- Targets with a complete result JSON (`probing_complete=True`) in the output directory are reused without re-probing by default.
- `--force` / `-F` re-probes all targets; it deletes only per-target `.json` files and the `.targets` manifest — never other files in the output directory.
- When `--force` would overwrite files, the CLI prints the absolute results directory and asks for confirmation (auto-skipped if stdin is not a TTY, or if `-y`/`--yes` is passed).
- A `.targets` manifest is written to the output directory on every run so the visualizer only loads results for the current target list.
- Both `results/` and `mock_results/` are in `.gitignore`.

## Behavior Quirks
- By default, the CLI launches the Dash server before probing starts, opens `http://localhost:8050`, and then blocks after probing so the UI stays up. Use `--no-viz` for non-interactive runs.
- Output is one JSON file per target under `results/` (named by the original target — domain names for domain targets, IPs for IP targets).
- Forward DNS resolution for target domains happens **before** probing starts; unresolvable domains are warned and skipped.
- Reverse DNS resolution (hop hostnames) happens **after** probing finishes for each target; partial JSON written during probing will not yet contain hostnames.
- Default probing sends UDP, TCP SYN, and ICMP for each TTL step unless `-P` restricts the protocol.

## Visualizer Interactivity
- Protocol checkboxes in the legend filter which protocol paths (UDP/TCP/ICMP) appear in the graph and charts.
- Click-to-focus: clicking a target node in the Cytoscape graph highlights its path by dimming unrelated nodes/edges to 12% opacity. Clicking the same target again or clicking the Source node restores the full view. This is driven by a `focused-target` `dcc.Store`.
- All Cytoscape elements must include an explicit `"classes": ""` key (even when empty) so Dash properly clears dynamic classes like `dimmed` on unfocus.
- Domain targets display as `"domain.com\n(resolved.ip)"` in the graph. The resolved IP node is merged into the target block, not shown as a separate node.

## Typecheck / Packaging Notes
- Python target is `>=3.12`.
- Ruff line length is `100`.
- `mypy` is configured with `explicit_package_bases = true` and `mypy_path = "."`; run it from the repo root as `uv run mypy src/ visualizer/ scripts/` to avoid module-path issues.
- `mypy` uses `disallow_untyped_defs = true` — all function signatures need type annotations.
- Dash callback data (e.g. `tapNodeData`) returns `Any`; cast or validate before use to satisfy mypy.
- The wheel package list only includes `src`; if packaging behavior matters, double-check whether `visualizer/` assets are included because the runtime currently imports `visualizer.app` directly from the repo.
