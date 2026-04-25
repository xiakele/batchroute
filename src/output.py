from __future__ import annotations

import os
import sys
from pathlib import Path

_NO_COLOR = not sys.stderr.isatty() or os.environ.get("NO_COLOR", "") != ""

_BOLD = "\033[1m" if not _NO_COLOR else ""
_DIM = "\033[2m" if not _NO_COLOR else ""
_RED = "\033[31m" if not _NO_COLOR else ""
_GREEN = "\033[32m" if not _NO_COLOR else ""
_YELLOW = "\033[33m" if not _NO_COLOR else ""
_CYAN = "\033[36m" if not _NO_COLOR else ""
_RESET = "\033[0m" if not _NO_COLOR else ""


def _c(text: str, *codes: str) -> str:
    return f"{''.join(codes)}{text}{_RESET}"


def bold(text: str) -> str:
    return _c(text, _BOLD)


def dim(text: str) -> str:
    return _c(text, _DIM)


def red(text: str) -> str:
    return _c(text, _RED)


def green(text: str) -> str:
    return _c(text, _GREEN)


def yellow(text: str) -> str:
    return _c(text, _YELLOW)


def cyan(text: str) -> str:
    return _c(text, _CYAN)


def heading(text: str) -> str:
    return bold(cyan(text))


def success(text: str) -> str:
    return green(text)


def warning(text: str) -> str:
    return yellow(text)


def error(text: str) -> str:
    return red(text)


def chown_to_invoking_user(path: Path) -> None:
    try:
        euid = os.geteuid()
    except AttributeError:
        return
    if euid != 0:
        return
    uid = os.environ.get("SUDO_UID")
    gid = os.environ.get("SUDO_GID")
    if uid is None or gid is None:
        return
    try:
        os.chown(path, int(uid), int(gid))
    except OSError:
        pass
