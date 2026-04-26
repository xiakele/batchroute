from __future__ import annotations

import ipaddress
import logging
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

from src.output import chown_to_invoking_user, dim, success, warning

logger = logging.getLogger(__name__)

CITY_DB_PATH = Path("data/GeoLite2-City.mmdb")
CITY_DB_URL = "https://git.io/GeoLite2-City.mmdb"

ASN_DB_PATH = Path("data/GeoLite2-ASN.mmdb")
ASN_DB_URL = "https://git.io/GeoLite2-ASN.mmdb"

_INTERNAL_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("::1/128"),
]


@dataclass
class GeoData:
    country_code: str | None = None
    city: str | None = None
    region: str | None = None
    lat: float | None = None
    lon: float | None = None
    asn_number: int | None = None
    asn_org: str | None = None
    is_internal: bool = False


def _is_internal_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        for network in _INTERNAL_NETWORKS:
            if addr in network:
                return True
        return False
    except ValueError:
        return False


def _download_db(url: str, path: Path) -> bool:
    try:
        with urlopen(url, timeout=30) as response:
            total_size = response.headers.get("Content-Length")
            if total_size is not None:
                total_size = int(total_size)
            downloaded = 0
            chunk_size = 8192
            with open(path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        percent = min(100, int(downloaded * 100 / total_size))
                        bar = "█" * (percent // 2) + "░" * (50 - percent // 2)
                        sys.stdout.write(f"\r  [{bar}] {percent}%")
                        sys.stdout.flush()
            if total_size:
                sys.stdout.write("\n")
                sys.stdout.flush()
        return True
    except Exception as exc:
        print(f"  {warning(f'Download failed: {exc}')}")
        return False


def download_geolite2_db(city: bool = True, asn: bool = True) -> tuple[bool, bool]:
    city_ok = True
    asn_ok = True

    if city and not CITY_DB_PATH.exists():
        if not CITY_DB_PATH.parent.exists():
            CITY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            chown_to_invoking_user(CITY_DB_PATH.parent)
        print(f"  {dim('Downloading GeoLite2-City database ...')}")
        city_ok = _download_db(CITY_DB_URL, CITY_DB_PATH)
        if city_ok:
            print(f"  {success('GeoLite2-City download complete.')}")

    if asn and not ASN_DB_PATH.exists():
        if not ASN_DB_PATH.parent.exists():
            ASN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            chown_to_invoking_user(ASN_DB_PATH.parent)
        print(f"  {dim('Downloading GeoLite2-ASN database ...')}")
        asn_ok = _download_db(ASN_DB_URL, ASN_DB_PATH)
        if asn_ok:
            print(f"  {success('GeoLite2-ASN download complete.')}")

    return city_ok, asn_ok


@lru_cache(maxsize=512)
def lookup_ip(ip: str) -> GeoData | None:
    if _is_internal_ip(ip):
        return GeoData(is_internal=True)

    if not CITY_DB_PATH.exists():
        return None

    try:
        import geoip2.database

        with geoip2.database.Reader(str(CITY_DB_PATH)) as reader:
            response = reader.city(ip)
            cc = response.country.iso_code
            city = response.city.name
            region = response.subdivisions.most_specific.name
            lat = response.location.latitude
            lon = response.location.longitude
            return GeoData(
                country_code=cc,
                city=city,
                region=region,
                lat=lat,
                lon=lon,
                is_internal=False,
            )
    except Exception as exc:
        logger.debug("Geo lookup failed for %s: %s", ip, exc)
        return None


@lru_cache(maxsize=512)
def lookup_asn(ip: str) -> GeoData | None:
    if _is_internal_ip(ip):
        return GeoData(is_internal=True)

    if not ASN_DB_PATH.exists():
        return None

    try:
        import geoip2.database

        with geoip2.database.Reader(str(ASN_DB_PATH)) as reader:
            response = reader.asn(ip)
            asn = response.autonomous_system_number
            org = response.autonomous_system_organization
            return GeoData(
                asn_number=asn,
                asn_org=org,
                is_internal=False,
            )
    except Exception as exc:
        logger.debug("ASN lookup failed for %s: %s", ip, exc)
        return None
