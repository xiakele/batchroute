from __future__ import annotations

import ipaddress
from pathlib import Path

import pandas as pd


def parse_targets(filepath: str) -> list[str]:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")

    ext = path.suffix.lower()
    if ext == ".csv":
        return _parse_csv(path)
    return _parse_txt(path)


def _parse_csv(path: Path) -> list[str]:
    df = pd.read_csv(path, header=None)
    ips = []
    for val in df.iloc[:, 0]:
        ip = str(val).strip()
        if _is_valid_ip(ip):
            ips.append(ip)
    return ips


def _parse_txt(path: Path) -> list[str]:
    ips = []
    for line in path.read_text().splitlines():
        ip = line.strip()
        if ip and _is_valid_ip(ip):
            ips.append(ip)
    return ips


def _is_valid_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except ValueError:
        return False
