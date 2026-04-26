from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.config import Protocol
from src.output import chown_to_invoking_user


@dataclass
class Hop:
    ttl: int
    protocol: Protocol
    ip: str | None = None
    hostname: str | None = None
    rtts: list[float | None] = field(default_factory=list)
    country_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    asn_number: int | None = None
    asn_org: str | None = None
    is_internal: bool = False

    @property
    def avg_rtt(self) -> float | None:
        values = [r for r in self.rtts if r is not None]
        return sum(values) / len(values) if values else None

    @property
    def loss_rate(self) -> float:
        lost = sum(1 for r in self.rtts if r is None)
        return lost / len(self.rtts) if self.rtts else 1.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["protocol"] = self.protocol.value
        d["avg_rtt"] = self.avg_rtt
        d["loss_rate"] = self.loss_rate
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Hop:
        d["protocol"] = Protocol(d["protocol"])
        return cls(
            **{
                k: v
                for k, v in d.items()
                if k in cls.__dataclass_fields__ and k != "avg_rtt" and k != "loss_rate"
            }
        )


@dataclass
class TracerouteResult:
    target: str
    hops: list[Hop] = field(default_factory=list)
    destination_reached: bool = False
    probing_complete: bool = False
    cached: bool = False
    resolved_ip: str | None = None
    country_code: str | None = None
    lat: float | None = None
    lon: float | None = None
    asn_number: int | None = None
    asn_org: str | None = None
    is_internal: bool = False

    def to_dict(self) -> dict:
        d = {
            "target": self.target,
            "resolved_ip": self.resolved_ip,
            "destination_reached": self.destination_reached,
            "probing_complete": self.probing_complete,
            "cached": self.cached,
            "hops": [h.to_dict() for h in self.hops],
            "country_code": self.country_code,
            "lat": self.lat,
            "lon": self.lon,
            "asn_number": self.asn_number,
            "asn_org": self.asn_org,
            "is_internal": self.is_internal,
        }
        if self.resolved_ip is None:
            del d["resolved_ip"]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TracerouteResult:
        return cls(
            target=d["target"],
            destination_reached=d.get("destination_reached", False),
            probing_complete=d.get("probing_complete", False),
            cached=d.get("cached", False),
            hops=[Hop.from_dict(h) for h in d.get("hops", [])],
            resolved_ip=d.get("resolved_ip"),
            country_code=d.get("country_code"),
            lat=d.get("lat"),
            lon=d.get("lon"),
            asn_number=d.get("asn_number"),
            asn_org=d.get("asn_org"),
            is_internal=d.get("is_internal", False),
        )

    def to_json(self, path: Path) -> None:
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            chown_to_invoking_user(path.parent)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_json(cls, path: Path) -> TracerouteResult:
        with open(path) as f:
            return cls.from_dict(json.load(f))
