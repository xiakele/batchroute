#!/usr/bin/env python3
"""Generate mock traceroute result JSON files for visualizer stress testing."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

DOMAIN_SUFFIXES = [
    ".com",
    ".net",
    ".org",
    ".io",
    ".co",
    ".dev",
    ".app",
    ".cloud",
    ".tech",
    ".info",
]

DOMAIN_PREFIXES = [
    "acme",
    "nexus",
    "apex",
    "nova",
    "orbit",
    "pulse",
    "helix",
    "vertex",
    "cipher",
    "flux",
    "atlas",
    "prism",
    "zenith",
    "vector",
    "quasar",
    "lambda",
    "omega",
    "sigma",
    "delta",
    "theta",
    "aurora",
    "beacon",
    "carbon",
    "drift",
    "echo",
    "forge",
    "glacier",
    "horizon",
    "ion",
    "jade",
    "krypton",
    "lunar",
    "magnet",
    "nebula",
    "onyx",
    "plasma",
    "quantum",
    "radar",
    "stellar",
    "titan",
    "ultra",
    "vortex",
    "warp",
    "xenon",
    "zephyr",
    "alpha",
    "bravo",
    "core",
    "datum",
    "ember",
    "frost",
    "gamma",
    "hydra",
    "infra",
    "jet",
    "karma",
    "lucid",
    "macro",
    "nano",
    "optic",
    "pixel",
    "rapid",
    "scaled",
    "turbo",
    "unity",
    "vivid",
    "wired",
    "xray",
    "yield",
    "zone",
]

SHARED_GATEWAYS: list[tuple[str, str | None]] = [
    ("192.168.1.1", "gateway.home"),
    ("10.0.0.1", "core-router.isp-a.net"),
    ("10.0.0.2", "edge-router.isp-a.net"),
    ("172.16.0.1", "transit-a.isp-b.net"),
    ("172.16.0.2", "transit-b.isp-b.net"),
    ("203.0.113.1", "peering.ixp-west.net"),
    ("203.0.113.2", "peering.ixp-east.net"),
    ("198.51.100.1", "backbone-a.carrier.net"),
    ("198.51.100.2", "backbone-b.carrier.net"),
    ("198.51.100.3", None),
    ("192.0.2.1", "hop-large.teleco.net"),
    ("192.0.2.2", None),
    ("100.64.0.1", "cg-nat.provider.net"),
    ("100.64.0.2", None),
    ("100.64.0.3", "relay.provider.net"),
]


_PUBLIC_FIRST_OCTETS = [
    10,
    23,
    31,
    45,
    51,
    64,
    66,
    72,
    80,
    89,
    93,
    104,
    108,
    111,
    142,
    151,
    157,
    162,
    172,
    176,
    185,
    192,
    198,
    203,
    209,
    216,
]


def _random_ip(rng: random.Random) -> str:
    first = rng.choice(_PUBLIC_FIRST_OCTETS)
    return f"{first}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}"


_ISP_DOMAINS = ["isp1.net", "isp2.com", "backbone.net", "carrier.org"]
_CRS = ["cr1", "cr2", "cr3"]
_CITIES = ["nyc", "sfo", "lax", "ord", "dfw", "sea"]
_PROVIDERS = ["isp1", "isp2", "bb1"]
_TLDS = ["net", "com"]
_ROLES = ["pe", "ce", "se"]
_POPS = ["pop1", "pop2"]


def _random_hostname(rng: random.Random) -> str:
    template = rng.randint(0, 2)
    if template == 0:
        return f"router-{rng.randint(1, 99)}.{rng.choice(_ISP_DOMAINS)}"
    if template == 1:
        return (
            f"ae{rng.randint(0, 9)}.{rng.choice(_CRS)}"
            f".{rng.choice(_CITIES)}.{rng.choice(_PROVIDERS)}"
            f".{rng.choice(_TLDS)}"
        )
    return (
        f"bundle-ether{rng.randint(0, 9)}.{rng.choice(_ROLES)}"
        f"{rng.randint(1, 9)}.{rng.choice(_POPS)}.{rng.choice(_TLDS)}"
    )


def _generate_domain_target(rng: random.Random) -> str:
    prefix = rng.choice(DOMAIN_PREFIXES)
    if rng.random() < 0.3:
        prefix = prefix + str(rng.randint(1, 99))
    suffix = rng.choice(DOMAIN_SUFFIXES)
    return f"{prefix}{suffix}"


def _generate_ip_target(rng: random.Random) -> str:
    return _random_ip(rng)


def _generate_hops(
    rng: random.Random,
    max_ttl: int,
    destination_reached: bool,
    dest_ip: str,
    shared_hop_count: int,
) -> list[dict]:
    hops: list[dict] = []
    protocols = ["udp", "tcp", "icmp"]

    per_ttl_ip: dict[int, str | None] = {}
    per_ttl_hostname: dict[int, str | None] = {}

    for ttl in range(1, max_ttl + 1):
        is_dest = ttl == max_ttl and destination_reached
        is_shared = ttl <= shared_hop_count

        if is_dest:
            per_ttl_ip[ttl] = dest_ip
            per_ttl_hostname[ttl] = None
        elif is_shared:
            idx = rng.randint(0, len(SHARED_GATEWAYS) - 1)
            gw_ip, gw_hostname = SHARED_GATEWAYS[idx]
            per_ttl_ip[ttl] = gw_ip
            per_ttl_hostname[ttl] = gw_hostname
        else:
            missing = rng.random() < 0.08
            if missing:
                per_ttl_ip[ttl] = None
                per_ttl_hostname[ttl] = None
            else:
                per_ttl_ip[ttl] = _random_ip(rng)
                per_ttl_hostname[ttl] = _random_hostname(rng) if rng.random() < 0.4 else None

    for ttl in range(1, max_ttl + 1):
        is_dest = ttl == max_ttl and destination_reached
        base_ip = per_ttl_ip[ttl]
        base_hostname = per_ttl_hostname[ttl]

        for protocol in protocols:
            ip: str | None = base_ip
            hostname: str | None = base_hostname

            if ip is not None and not is_dest:
                if rng.random() < 0.06:
                    ip = None
                    hostname = None

            if ip is not None and hostname is None and rng.random() < 0.25:
                hostname = _random_hostname(rng)

            base_rtt = 1.0 + ttl * rng.uniform(1.8, 3.5)
            if protocol == "tcp":
                base_rtt += rng.uniform(0.1, 0.5)

            rtts: list[float | None] = []
            for q in range(3):
                if ip is None:
                    rtts.append(None)
                elif rng.random() < 0.07:
                    rtts.append(None)
                else:
                    jitter = rng.uniform(-0.5, 0.8)
                    rtts.append(max(0.1, round(base_rtt + jitter, 3)))

            values = [r for r in rtts if r is not None]
            avg_rtt = round(sum(values) / len(values), 3) if values else None
            loss_rate = sum(1 for r in rtts if r is None) / len(rtts)

            hops.append(
                {
                    "ttl": ttl,
                    "protocol": protocol,
                    "ip": ip,
                    "hostname": hostname,
                    "rtts": rtts,
                    "avg_rtt": avg_rtt,
                    "loss_rate": loss_rate,
                }
            )

    return hops


def generate_route(
    rng: random.Random,
    target: str,
    resolved_ip: str | None,
) -> dict:
    max_ttl = rng.randint(5, 18)
    destination_reached = rng.random() < 0.8
    shared_hop_count = rng.randint(1, 3)

    dest_ip = resolved_ip if resolved_ip else _random_ip(rng)

    hops = _generate_hops(rng, max_ttl, destination_reached, dest_ip, shared_hop_count)

    result: dict = {
        "target": target,
        "destination_reached": destination_reached,
        "probing_complete": True,
        "cached": False,
        "hops": hops,
    }
    if resolved_ip is not None:
        result["resolved_ip"] = resolved_ip

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate mock traceroute result JSON files for visualizer stress testing.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of mock routes to generate (default: 100).",
    )
    parser.add_argument(
        "--output-dir",
        default="mock_results",
        help="Output directory for JSON files and .targets manifest (default: mock_results/).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible output.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing JSON/targets files without prompting.",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    output_dir = Path(args.output_dir)

    existing_json = list(output_dir.glob("*.json")) if output_dir.exists() else []
    existing_manifest = (output_dir / ".targets").exists() if output_dir.exists() else False

    if existing_json or existing_manifest:
        if not args.force:
            if not sys.stdin.isatty():
                print(
                    f"Output directory {output_dir.resolve()} contains existing files. "
                    "Use --force to overwrite.",
                )
                sys.exit(1)
            prompt = (
                f"Output directory {output_dir.resolve()} "
                "contains existing files. Overwrite? [y/N] "
            )
            answer = input(prompt)
            if answer.strip().lower() not in ("y", "yes"):
                print("Aborted.")
                sys.exit(0)

        output_dir.mkdir(parents=True, exist_ok=True)
        for jf in output_dir.glob("*.json"):
            jf.unlink()
        (output_dir / ".targets").unlink(missing_ok=True)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)

    targets: list[str] = []
    used_names: set[str] = set()

    for _ in range(args.count):
        if rng.random() < 0.6:
            target = _generate_domain_target(rng)
            while target in used_names:
                target = _generate_domain_target(rng)
            resolved_ip = _random_ip(rng)
        else:
            target = _generate_ip_target(rng)
            resolved_ip = None

        used_names.add(target)
        targets.append(target)

        result = generate_route(rng, target, resolved_ip)
        path = output_dir / f"{target}.json"
        with open(path, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

    (output_dir / ".targets").write_text("\n".join(targets) + "\n")

    print(f"Generated {len(targets)} mock route(s) in {output_dir.resolve()}")


if __name__ == "__main__":
    main()
