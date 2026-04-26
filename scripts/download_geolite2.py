from __future__ import annotations

import urllib.request
from pathlib import Path

URL = "https://git.io/GeoLite2-City.mmdb"
DEST = Path("data/GeoLite2-City.mmdb")


def main() -> None:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading GeoLite2-City database to {DEST} ...")
    urllib.request.urlretrieve(URL, DEST)
    print(f"Done. Saved {DEST.stat().st_size:,} bytes.")


if __name__ == "__main__":
    main()
