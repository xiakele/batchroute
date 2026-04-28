#!/usr/bin/env python3
# ruff: noqa: E501
"""Generate release notes markdown for GitHub releases."""

import os


def main() -> None:
    tag = os.environ["GITHUB_REF_NAME"]
    version = tag.lstrip("v")
    repo = os.environ["GITHUB_REPOSITORY"]
    url_base = f"https://github.com/{repo}/releases/download/{tag}"

    body = f"""## batchroute {tag}

Batch traceroute tool with topology visualization.

### Downloads

| Platform | Architecture | Archive |
|----------|--------------|---------|
| Linux | x86_64 | [batchroute-{version}-linux-x86_64.tar.gz]({url_base}/batchroute-{version}-linux-x86_64.tar.gz) |
| macOS | ARM64 | [batchroute-{version}-macos-arm64.tar.gz]({url_base}/batchroute-{version}-macos-arm64.tar.gz) |
| macOS | Intel (x86_64) | [batchroute-{version}-macos-x86_64.tar.gz]({url_base}/batchroute-{version}-macos-x86_64.tar.gz) |
| Windows | x86_64 | [batchroute-{version}-windows-x86_64.zip]({url_base}/batchroute-{version}-windows-x86_64.zip) |

### Platform Notes

- **Linux / macOS:** The binary requires root (or `CAP_NET_RAW`) for raw packet transmission.
- **Windows:** Please install [Npcap](https://npcap.com/) (or WinPcap) beforehand, or have [Wireshark](https://www.wireshark.org/) installed.

### Quick Start

```bash
# Extract and run
./batchroute --help

# Example probe
sudo ./batchroute 1.1.1.1
sudo ./batchroute -f targets.txt
```
"""

    with open("release-notes.md", "w") as f:
        f.write(body)


if __name__ == "__main__":
    main()
