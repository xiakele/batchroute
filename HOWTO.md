# HOWTO — Install and Run batchroute

## Requirements

- **Python** >= 3.12
- **uv** (recommended) or `pip` with a virtual environment
- **Root / Administrator privileges** when performing real packet probes, because scapy sends raw packets
  - Linux: run with `sudo`
  - macOS: run with `sudo`
  - Windows: run as Administrator

## 1. Install Dependencies

The project uses `pyproject.toml` and `uv` for dependency management.

```bash
# Clone or extract the project, then navigate into it
cd batchroute

# Sync dependencies (creates .venv automatically)
uv sync
```

If you prefer plain `pip`:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -e ".[dev]"
```

## 2. Prepare a Target List

Create a plain text file (`targets.txt`) with one IP address or domain per line:

```text
1.1.1.1
8.8.8.8
example.com
cloudflare.com
```

Or use a CSV file (`targets.csv`) where the first column contains the targets:

```csv
1.1.1.1
8.8.8.8
example.com
```

## 3. Run the Traceroute

### Basic usage (with visualization)

```bash
# Linux — root required for raw packets
sudo $(which uv) run batchroute -f targets.txt
```

On success the CLI will:
1. Resolve domains.
2. Launch the visualizer at `http://localhost:8050` and open your browser.
3. Begin probing in parallel.
4. Block after probing so the UI stays up. Press `Ctrl+C` to exit.

### Common options

| Flag | Description | Default |
|------|-------------|---------|
| `-f FILE` | Input file (`.txt` or `.csv`) | **required** |
| `-m N` | Maximum TTL | 30 |
| `-M N` | Minimum / starting TTL | 1 |
| `-q N` | Probe series (queries) per TTL step | 3 |
| `-p PORT` | Destination port for UDP/TCP probes | 33434 |
| `-z SEC` | Wait time between consecutive probes | 0.0 |
| `--size BYTES` | Total packet size | 60 |
| `--timeout SEC` | Timeout per probe response | 5.0 |
| `-n` | Skip reverse-DNS lookups | off |
| `-P {udp,tcp,icmp}` | Probe only one protocol | all three |
| `-o DIR` | Output directory for JSON results | `results/` |
| `-F` | Force re-probe; ignore cached results | off |
| `-y` | Skip overwrite confirmation when using `-F` | off |
| `--no-viz` | Do not launch the visualizer | off |
| `-w N` | Parallel worker threads | 4 |

### Examples

Probe only ICMP, 5 queries per TTL, max TTL 20:

```bash
sudo $(which uv) run batchroute -f targets.txt -P icmp -q 5 -m 20
```

Run non-interactively (no browser UI) with a custom output directory:

```bash
sudo $(which uv) run batchroute -f targets.txt --no-viz -o ./my_results
```

Force re-run everything without prompting:

```bash
sudo $(which uv) run batchroute -f targets.txt -F -y
```

## 4. View Results in the Visualizer (Standalone)

If you already have JSON results and only want to open the UI:

```bash
uv run python -m visualizer.app --results-dir results/
```

Then open `http://localhost:8050` in your browser.

The visualizer reads every `.json` file in the directory and the `.targets` manifest (if present). It polls for changes every 2 seconds, so you can leave it open while a separate probing process is still writing files.

## 5. Generate Mock Data for Testing

If you want to test the visualizer without sending real packets:

```bash
uv run python scripts/generate_mock_routes.py --count 100 --seed 42
```

This creates 100 fake routes in `mock_results/`. Launch the visualizer against them:

```bash
uv run python -m visualizer.app --results-dir mock_results/
```

## 6. Development / Quality Checks

Run the linting and type-checking pipeline:

```bash
uv run ruff check src/ visualizer/ scripts/
uv run ruff format --check src/ visualizer/ scripts/
uv run mypy src/ visualizer/ scripts/
```

Or run the full pre-commit suite:

```bash
uv run pre-commit run --all-files
```

## Troubleshooting

- **Permission denied / raw socket errors**: Make sure you run with `sudo` on Linux/macOS or as Administrator on Windows.
- **Npcap broadcast warnings on Windows**: The tool pre-seeds the ARP cache automatically; if warnings persist, ensure Npcap is installed and your interface is active.
- **Visualizer shows “Waiting for probe data…”**: Verify the `--results-dir` path matches where JSON files are being written, and check that the `.targets` manifest exists.
- **Domain resolution fails**: The tool skips unresolvable domains with a warning. Check your DNS connectivity or use `-n` to disable reverse lookups after probing.
