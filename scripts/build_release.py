#!/usr/bin/env python3
"""Build release binaries locally using PyInstaller."""

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    spec_file = repo_root / "batchroute.spec"

    print("Building release binaries with PyInstaller...")
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "-y", str(spec_file)],
            check=True,
            cwd=repo_root,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Build failed with exit code {exc.returncode}", file=sys.stderr)
        return 1

    dist_dir = repo_root / "dist" / "batchroute"
    if not dist_dir.exists():
        print(f"Error: Expected dist directory not found at {dist_dir}", file=sys.stderr)
        return 1

    archive_base = repo_root / "dist" / "batchroute-release"
    archive_path = shutil.make_archive(
        str(archive_base),
        "gztar",
        root_dir=dist_dir.parent,
        base_dir="batchroute",
    )
    print(f"Created archive: {archive_path}")
    print(f"Extract and run: ./{dist_dir.name}/batchroute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
