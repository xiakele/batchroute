# How to Use batchroute

## Quick Start with a Pre-Built Binary

The easiest way to run **batchroute** is to download a pre-built binary from [GitHub Releases](https://github.com/xiakele/batchroute/releases).

1. Download the archive that matches your operating system.
2. Extract it with an archive manager, or use the following commands:
   ```bash
   # Linux / macOS
   tar -xzf batchroute-*.tar.gz
   cd batchroute/

   # Windows (PowerShell)
   Expand-Archive batchroute-*.zip -DestinationPath batchroute
   cd batchroute
   ```
3. Run the tool inside its directory:
   ```bash
   # Linux / macOS — use sudo
   sudo ./batchroute 1.1.1.1 google.com

   # Windows — run PowerShell / CMD as Administrator
   .\batchroute.exe 1.1.1.1 google.com
   ```

### Platform Notes

| Platform | Requirements |
|----------|--------------|
| **Linux / macOS** | `sudo` (raw socket restriction). |
| **Windows** | Install [Npcap](https://npcap.com/) (or WinPcap) beforehand, or have [Wireshark](https://www.wireshark.org/) installed. |

---

## Basic Usage

### Probe a single target
```bash
sudo ./batchroute 8.8.8.8
```

### Probe multiple targets
```bash
sudo ./batchroute 1.1.1.1 google.com example.com
```

### Probe from a file
Create a text file with one target per line (IPs or domains):

targets.txt:


```
1.1.1.1
google.com
cloudflare.com
```

Then run:
```bash
sudo ./batchroute -f targets.txt
```

CSV files are also supported (first column is read).

---

## Visualizer

By default, after probing starts **batchroute** launches a background Dash server and opens your browser at `http://localhost:8050`.

- **Protocol filtering** — Toggle UDP, TCP, and ICMP paths in the legend.
- **Click-to-focus** — Click on a node to highlight the routes through that node; click again (or click the Source node) to restore the full graph. The details of the node (IP, Location, Average RTT...) are displayed on the side panel.
- **Live updates** — The UI polls the output directory every 2 seconds, so new results appear automatically.

To run without the UI:
```bash
sudo ./batchroute --no-viz -f targets.txt
```

---

## Common Options

You can run `./batchroute --help` to view the full options list.

| Flag | Description | Default |
|------|-------------|---------|
| `-m N` | Maximum TTL | 30 |
| `-M N` | Minimum TTL | 1 |
| `-q N` | Queries per TTL step | 3 |
| `-p PORT` | Destination port (UDP/TCP) | 33434 |
| `-z SEC` | Wait between probes | 0.005 s |
| `--timeout SEC` | Per-probe timeout | 3.0 s |
| `-N N` | Max in-flight probes per target | 32 |
| `-P {udp,tcp,icmp}` | Restrict to one protocol | all three |
| `-o DIR` | Output directory | `results/` |
| `-F` / `--force` | Re-probe all targets, ignore cache | off |
| `-y` / `--yes` | Skip confirmation when using `--force` | off |
| `--no-viz` | Do not launch the visualizer | off |
| `--no-geo` | Skip GeoIP lookups | off |
| `--iface NAME` | Network interface to use | default route |
| `--list-interfaces` | Show available interfaces and exit | — |
| `-w N` | Parallel worker threads | 4 |
| `-n` / `--no-dns` | Skip reverse DNS for hops | off |

**Example with options:**
```bash
sudo ./batchroute -m 20 -P icmp -F -y -o ./my_results 8.8.8.8
```

---

## Troubleshooting

### "Raw socket access is required"
You are not running with sufficient privileges.
- **Linux / macOS:** use `sudo` or grant the binary `CAP_NET_RAW`.
- **Windows:** right-click your terminal and choose **Run as Administrator**.

### "No connected interface with a default route found"
The tool could not auto-detect a usable network interface. List them and pick one manually:
```bash
sudo ./batchroute --list-interfaces
sudo ./batchroute --iface eth0 -f targets.txt
```

### GeoIP lookups are missing
On the first run the tool will prompt you to download the GeoLite2 databases.
Use `--no-geo` to skip GeoIP entirely.

---

## Development Setup

If you prefer to run from source or contribute, install the development environment:

### Prerequisites
- Python **≥ 3.12**
- [`uv`](https://docs.astral.sh/uv/) package manager

### Install dependencies
```bash
uv sync
```

### Run from source
```bash
# General help
uv run batchroute --help

# Probe with root (Linux)
sudo $(which uv) run batchroute -f targets.txt
```

### Code quality checks
```bash
uv run ruff check src/ visualizer/ scripts/
uv run ruff format --check src/ visualizer/ scripts/
uv run mypy src/ visualizer/ scripts/
uv run pre-commit run --all-files
```

### Build a release binary locally
```bash
uv run python scripts/build_release.py
```
