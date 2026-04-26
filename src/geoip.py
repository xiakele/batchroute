from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("data/GeoLite2-City.mmdb")

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
    lat: float | None = None
    lon: float | None = None
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


@lru_cache(maxsize=512)
def lookup_ip(ip: str) -> GeoData | None:
    if _is_internal_ip(ip):
        return GeoData(is_internal=True)

    if not DB_PATH.exists():
        logger.warning("GeoLite2 database not found at %s — geo lookup skipped", DB_PATH)
        return None

    try:
        import geoip2.database

        with geoip2.database.Reader(str(DB_PATH)) as reader:
            response = reader.city(ip)
            cc = response.country.iso_code
            lat = response.location.latitude
            lon = response.location.longitude
            return GeoData(
                country_code=cc,
                lat=lat,
                lon=lon,
                is_internal=False,
            )
    except Exception as exc:
        logger.debug("Geo lookup failed for %s: %s", ip, exc)
        return None
