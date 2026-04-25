from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import pandas as pd

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9._-]*[a-zA-Z0-9])?$")


def parse_targets(filepath: str) -> tuple[list[str], list[str]]:
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")

    ext = path.suffix.lower()
    if ext == ".csv":
        return _parse_csv(path)
    return _parse_txt(path)


def _parse_csv(path: Path) -> tuple[list[str], list[str]]:
    df = pd.read_csv(path, header=None)
    targets: list[str] = []
    invalid: list[str] = []
    for val in df.iloc[:, 0]:
        entry = str(val).strip()
        if is_valid_target(entry):
            targets.append(entry)
        elif entry:
            invalid.append(entry)
    return targets, invalid


def _parse_txt(path: Path) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    invalid: list[str] = []
    for line in path.read_text().splitlines():
        entry = line.strip()
        if not entry:
            continue
        if is_valid_target(entry):
            targets.append(entry)
        else:
            invalid.append(entry)
    return targets, invalid


def is_valid_target(addr: str) -> bool:
    if _is_valid_ip(addr):
        return True
    return _looks_like_hostname(addr)


def _is_valid_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except ValueError:
        return False


def _looks_like_hostname(addr: str) -> bool:
    if not _HOSTNAME_RE.match(addr):
        return False
    if "." not in addr:
        return False
    if addr.startswith(".") or addr.endswith("."):
        return False
    for label in addr.split("."):
        if not label:
            return False
        if label.startswith("-") or label.endswith("-"):
            return False
        if len(label) > 63:
            return False
    return True
