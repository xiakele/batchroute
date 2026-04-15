# Agent Guide — batchroute

## Quick Start
- **Sync dependencies**: `uv sync`
- **Run prober + visualizer**: `sudo $(which uv) run batchroute -f test.txt`
  - *Note*: `sudo` is required on Linux for `scapy` to send raw packets.
- **Run visualizer standalone**: `uv run python -m visualizer.app --results-dir results/`

## Architecture & Data Flow
- **Entry point**: `src/main.py` (cli: `batchroute`)
- **Probing**: `src/prober.py` uses `scapy` to send UDP/TCP-SYN/ICMP probes in parallel.
- **Visualization**: `visualizer/app.py` is a Dash app that polls the `results/` directory for JSON files.
- **Progressive Updates**: The prober writes partial JSON results to `results/` after every hop. The visualizer (polling every 2s) renders these in real-time.
- **Shared Hops**: The visualizer merges intermediate hops with the same IP into a single node to form a clean source-path tree.

## High-Signal Constraints
- **Python Version**: Target is `>=3.12` (locked in `pyproject.toml`).
- **Permissions**: `scapy` **will fail** without root/capabilities on most systems. If you see socket errors, you likely forgot `sudo`.
- **Dash Logging**: Werkzeug logs are suppressed in `visualizer/app.py` to keep the CLI clean.
- **Poll Interval**: Dash uses a 2-second interval for filesystem polling.

## Verification
- There are currently no automated unit tests.
- Verify changes by running `uv run batchroute --help` and testing with `test.txt`.
- Check `results/*.json` to verify the data structure.
