from __future__ import annotations

import urllib.request
from pathlib import Path

from src.output import chown_to_invoking_user

CITY_URL = "https://git.io/GeoLite2-City.mmdb"
CITY_DEST = Path("data/GeoLite2-City.mmdb")

ASN_URL = "https://git.io/GeoLite2-ASN.mmdb"
ASN_DEST = Path("data/GeoLite2-ASN.mmdb")


def main() -> None:
    CITY_DEST.parent.mkdir(parents=True, exist_ok=True)
    chown_to_invoking_user(CITY_DEST.parent)

    print(f"Downloading GeoLite2-City database to {CITY_DEST} ...")
    urllib.request.urlretrieve(CITY_URL, CITY_DEST)
    chown_to_invoking_user(CITY_DEST)
    print(f"Done. Saved {CITY_DEST.stat().st_size:,} bytes.")

    print(f"Downloading GeoLite2-ASN database to {ASN_DEST} ...")
    urllib.request.urlretrieve(ASN_URL, ASN_DEST)
    chown_to_invoking_user(ASN_DEST)
    print(f"Done. Saved {ASN_DEST.stat().st_size:,} bytes.")


if __name__ == "__main__":
    main()
