from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.config import Protocol


@dataclass
class Hop:
    ttl: int
    protocol: Protocol
    ip: str | None = None
    hostname: str | None = None
    rtts: list[float | None] = field(default_factory=list)

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

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "destination_reached": self.destination_reached,
            "probing_complete": self.probing_complete,
            "hops": [h.to_dict() for h in self.hops],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TracerouteResult:
        return cls(
            target=d["target"],
            destination_reached=d.get("destination_reached", False),
            probing_complete=d.get("probing_complete", False),
            hops=[Hop.from_dict(h) for h in d.get("hops", [])],
        )

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_json(cls, path: Path) -> TracerouteResult:
        with open(path) as f:
            return cls.from_dict(json.load(f))
