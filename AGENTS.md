# Agent Guide — batchroute

## Commands
- Sync deps with `uv sync` (`uv.lock` is committed; keep it in sync after dependency changes).
- CLI entrypoint is `uv run batchroute ...`.
- Real packet probing needs root on Linux because `scapy` sends raw packets. Use `sudo $(which uv) run batchroute -f <targets-file>` for end-to-end prober tests.
- Standalone visualizer: `uv run python -m visualizer.app --results-dir results/`.
- Mock data generator (visualizer stress testing): `uv run python scripts/generate_mock_routes.py [--count 100] [--seed N] [--force]`.

## Verification Order
- `uv run ruff check src/ visualizer/ scripts/`
- `uv run ruff format --check src/ visualizer/ scripts/`
- `uv run mypy src/ visualizer/ scripts/`
- Full pre-commit run: `uv run pre-commit run --all-files`
- There are no automated tests beyond lint / typecheck. For behavior checks, use `uv run batchroute --help` or a manual probe with a small targets file.
- **Note:** pre-commit runs mypy in an isolated venv with `additional_dependencies: [pandas-stubs, dnspython, types-Flask]`. If mypy passes locally but fails in pre-commit, missing stubs in the isolated env are the likely cause.

## Repo Structure
- `src/main.py` — sole CLI entrypoint; wires the whole flow.
- `src/config.py` — constants and the `Protocol` enum (`udp`, `tcp`, `icmp`).
- `src/parser.py` — validates targets as IPs or hostnames; syntactically invalid entries are silently skipped.
- `src/resolver.py` — forward DNS (`resolve_hostname`) and reverse DNS (`resolve_single_ip`). Both caches are cleared by `clear_cache()`.
- `src/prober.py` — writes partial JSON updates during probing. `ProbeConfig.resolved_ip` is set for domain targets so scapy sends to the IP while `TracerouteResult.target` keeps the original domain name.
- `src/models.py` — `TracerouteResult` carries `cached` and `resolved_ip`. `resolved_ip` is serialized between `target` and `destination_reached` in JSON.
- `src/output.py` — terminal color helpers used by the CLI reporter.
- `visualizer/app.py` — Dash app polling `results/` every 2 s.
- `visualizer/assets/` — CSS and JS files auto-served by Dash. Any `.js` placed here is loaded in the page automatically.
- `visualizer/styles.py` — design tokens, Plotly layout, and Cytoscape stylesheet.
- `scripts/generate_mock_routes.py` — outputs to `mock_results/` by default.
- `scripts/build_release.py` — wrapper around PyInstaller that also creates `dist/batchroute-release.tar.gz`.

## Caching & Output
- Targets with a complete result JSON (`probing_complete=True`) in the output directory are reused without re-probing by default.
- `--force` / `-F` re-probes all targets; it deletes only per-target `.json` files and the `.targets` manifest — never other files in the output directory.
- When `--force` would overwrite files, the CLI prints the absolute results directory and asks for confirmation (auto-skipped if stdin is not a TTY, or if `-y`/`--yes` is passed).
- A `.targets` manifest is written to the output directory on every run so the visualizer knows which JSON files belong to the current target list.
- Both `results/` and `mock_results/` are in `.gitignore`.

## Behavior Quirks
- By default, the CLI launches the Dash server before probing starts, opens `http://localhost:8050`, and then blocks after probing so the UI stays up. Use `--no-viz` for non-interactive runs.
- Output is one JSON file per target under `results/` (named by the original target — domain names for domain targets, IPs for IP targets).
- Forward DNS resolution for target domains happens **before** probing starts; unresolvable domains are warned and skipped in `main.py`.
- Reverse DNS resolution (hop hostnames) happens **after** probing finishes for each target; partial JSON written during probing will not yet contain hostnames.
- Default probing sends UDP, TCP SYN, and ICMP for each TTL step unless `-P` restricts the protocol.
- Scapy sends packets via the interface associated with the default route (`0.0.0.0`). Use `--iface <name>` to override, or `--list-interfaces` to see available adapters.

## Visualizer Interactivity
- Protocol checkboxes in the legend filter which protocol paths appear in the graph and charts.
- Click-to-focus: clicking a target node highlights its path by dimming unrelated nodes/edges to 12% opacity. Clicking the same target again or clicking the Source node restores the full view. Driven by a `focused-node` `dcc.Store`.
- All Cytoscape elements must include an explicit `"classes": ""` key (even when empty) so Dash properly clears dynamic classes like `dimmed` on unfocus.
- Domain targets display as `"domain.com\n(resolved.ip)"` in the graph. The resolved IP node is merged into the target block, not shown separately.
- **Dash-cytoscape gotcha:** the `global` prop (used to expose the `cy` instance on `window`) is not supported in the version 1.0.2 Python wrapper. If you need to access the underlying Cytoscape instance from JS, traverse the React fiber from the DOM node or use a standalone JS asset in `visualizer/assets/` instead.

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
- **Platform caveats:**
  - **Linux / macOS:** The binary still requires root (or `CAP_NET_RAW`) for raw packet transmission; this is an OS restriction, not a packaging bug.
  - **Windows:** End users must install **Npcap** (or WinPcap) beforehand; the driver cannot be bundled.
  - **All platforms:** Bundle size is ~200–400 MB because of Pandas, Plotly, and Scapy.
- Smoke-test a fresh build with `./dist/batchroute/batchroute --help` and a quick probe (`--no-viz`) before publishing.
