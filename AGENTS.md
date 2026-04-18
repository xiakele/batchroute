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

## Behavior Quirks
- By default, the CLI launches the Dash server before probing starts, opens `http://localhost:8050`, and then blocks after probing so the UI stays up. Use `--no-viz` for non-interactive runs.
- Output is one JSON file per target under `results/` unless `--output-dir` is provided.
- DNS resolution happens after probing finishes for a target; partial JSON during probing may not have hostnames yet.
- Default probing sends UDP, TCP SYN, and ICMP for each TTL step unless `-P` restricts the protocol.

## Typecheck / Packaging Notes
- Python target is `>=3.12`.
- `mypy` is configured with `explicit_package_bases = true` and `mypy_path = "."`; run it from the repo root as `uv run mypy src/ visualizer/` to avoid module-path issues.
- The wheel package list only includes `src`; if packaging behavior matters, double-check whether `visualizer/` assets are included because the runtime currently imports `visualizer.app` directly from the repo.
