# Agent Guide — batchroute

## Commands
- Sync deps with `uv sync`.
- CLI entrypoint is `uv run batchroute ...`.
- Real packet probing needs root on Linux because `scapy` sends raw packets. Use `sudo $(which uv) run batchroute -f <targets-file>` when exercising the prober end-to-end.
- Standalone visualizer: `uv run python -m visualizer.app --results-dir results/`.

## Verification Order
- Run `uv run ruff check src/ visualizer/`.
- Run `uv run ruff format --check src/ visualizer/`.
- Run `uv run mypy src/ visualizer/`.
- `pre-commit` is installed and enforces the same checks plus whitespace / EOF fixers on every commit. Full run: `uv run pre-commit run --all-files`.
- There are no automated tests beyond lint / typecheck. For behavior checks, use `uv run batchroute --help` or a manual probe with a small targets file.

## Repo Structure
- `src/main.py` is the only CLI entrypoint and wires the whole flow.
- `src/prober.py` handles probing and writes partial JSON updates during probing, not just a final file.
- `visualizer/app.py` is a Dash app that polls `results/` every 2 seconds and is designed to show nodes appearing in real time.
- Visualizer styling is split between `visualizer/assets/style.css` (page CSS auto-served by Dash) and `visualizer/styles.py` (design tokens, Plotly layout, Cytoscape stylesheet).
- `TracerouteResult` in `src/models.py` has a `cached` field; once set, it persists to JSON and is used by the visualizer to distinguish cached vs fresh results.

## Caching & Output
- Targets with a complete result JSON (`probing_complete=True`) in the output directory are reused without re-probing by default.
- `--force` / `-F` re-probes all targets; it deletes only per-target `.json` files and the `.targets` manifest — never other files in the output directory.
- When `--force` would overwrite files, the CLI prints the absolute results directory and asks for confirmation (auto-skipped if stdin is not a TTY, or if `-y`/`--yes` is passed).
- A `.targets` manifest is written to the output directory on every run so the visualizer only loads results for the current target list.

## Behavior Quirks
- By default, the CLI launches the Dash server before probing starts, opens `http://localhost:8050`, and then blocks after probing so the UI stays up. Use `--no-viz` for non-interactive runs.
- Output is one JSON file per target under `results/` unless `--output-dir` is provided.
- DNS resolution happens after probing finishes for a target; partial JSON during probing may not have hostnames yet.
- Default probing sends UDP, TCP SYN, and ICMP for each TTL step unless `-P` restricts the protocol.

## Typecheck / Packaging Notes
- Python target is `>=3.12`.
- `mypy` is configured with `explicit_package_bases = true` and `mypy_path = "."`; run it from the repo root as `uv run mypy src/ visualizer/` to avoid module-path issues.
- The wheel package list only includes `src`; if packaging behavior matters, double-check whether `visualizer/` assets are included because the runtime currently imports `visualizer.app` directly from the repo.
