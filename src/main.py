from __future__ import annotations

import argparse
import ipaddress
import socket
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scapy.config import conf as scapy_conf

from src.config import (
    ALL_PROTOCOLS,
    DEFAULT_MAX_TTL,
    DEFAULT_MIN_TTL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PACKET_SIZE,
    DEFAULT_PORT,
    DEFAULT_QUERIES,
    DEFAULT_TIMEOUT,
    DEFAULT_WAIT,
    Protocol,
)
from src.models import TracerouteResult
from src.output import (
    bold,
    chown_to_invoking_user,
    cyan,
    dim,
    error,
    green,
    heading,
    red,
    warning,
)
from src.parser import is_valid_target, parse_targets
from src.prober import ProbeConfig, trace_single_target
from src.resolver import clear_cache, resolve_hostname, resolve_result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="batchroute",
        description="Batch traceroute tool with topology visualization.",
    )

    p.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help="One or more target IP addresses or domain names.",
    )
    p.add_argument(
        "-f",
        "--input-file",
        default=None,
        help=(
            "Path to a .txt or .csv file containing target IP addresses or domain names"
            " (alternative to positional targets)."
        ),
    )
    p.add_argument(
        "-m",
        "--max-ttl",
        type=int,
        default=DEFAULT_MAX_TTL,
        help=f"Maximum TTL (default: {DEFAULT_MAX_TTL}).",
    )
    p.add_argument(
        "-M",
        "--min-ttl",
        type=int,
        default=DEFAULT_MIN_TTL,
        help=f"Minimum TTL / starting TTL (default: {DEFAULT_MIN_TTL}).",
    )
    p.add_argument(
        "-q",
        "--queries",
        type=int,
        default=DEFAULT_QUERIES,
        help=f"Number of probe series per TTL step (default: {DEFAULT_QUERIES}).",
    )
    p.add_argument(
        "-p",
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Destination port for UDP/TCP probes (default: {DEFAULT_PORT}).",
    )
    p.add_argument(
        "-z",
        "--wait",
        type=float,
        default=DEFAULT_WAIT,
        help=f"Wait time in seconds between consecutive probes (default: {DEFAULT_WAIT}).",
    )
    p.add_argument(
        "--size",
        type=int,
        default=DEFAULT_PACKET_SIZE,
        help=f"Total packet size in bytes (default: {DEFAULT_PACKET_SIZE}).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds per probe response (default: {DEFAULT_TIMEOUT}).",
    )
    p.add_argument(
        "-n",
        "--no-dns",
        action="store_true",
        help="Do not resolve IP addresses to hostnames.",
    )
    p.add_argument(
        "-P",
        "--protocol",
        choices=["udp", "tcp", "icmp"],
        default=None,
        help="Restrict probing to a single protocol (default: all three).",
    )
    p.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write JSON results (default: {DEFAULT_OUTPUT_DIR}).",
    )
    p.add_argument(
        "-F",
        "--force",
        action="store_true",
        help="Re-probe all targets, ignoring cached results.",
    )
    p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when using --force.",
    )
    p.add_argument(
        "--no-viz",
        action="store_true",
        help="Skip launching the visualizer after probing.",
    )
    p.add_argument(
        "-w",
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers for probing (default: 4).",
    )
    p.add_argument(
        "-i",
        "--iface",
        default=None,
        help="Network interface to use for probing (default: interface for the default route).",
    )
    p.add_argument(
        "--list-interfaces",
        action="store_true",
        help="List available network interfaces and exit.",
    )

    return p


def _protocol_from_arg(val: str | None) -> list[Protocol]:
    if val is None:
        return list(ALL_PROTOCOLS)
    return [Protocol(val)]


def _start_visualizer(results_dir: str, targets: set[str] | None) -> None:
    from visualizer.app import create_app

    app = create_app(results_dir=results_dir, targets=targets)
    app.run(host="0.0.0.0", port=8050, debug=False, use_reloader=False)


def _launch_visualizer_background(results_dir: Path, targets: set[str]) -> None:
    thread = threading.Thread(
        target=_start_visualizer, args=(str(results_dir), targets), daemon=True
    )
    thread.start()
    time.sleep(1.5)
    viz_url = bold("http://localhost:8050")
    print(f"\n{cyan(bold('Visualizer'))} running at {viz_url} — press Ctrl+C to exit.")
    webbrowser.open("http://localhost:8050")


def _is_ip(addr: str) -> bool:
    try:
        ipaddress.ip_address(addr)
        return True
    except ValueError:
        return False


def _list_interfaces() -> None:
    print(heading("Available interfaces"))
    try:
        for iface in scapy_conf.ifaces.values():
            name = getattr(iface, "name", str(iface))
            ip = getattr(iface, "ip", "N/A")
            mac = getattr(iface, "mac", "N/A")
            print(f"  {name:<30} {ip:<15} {mac}")
    except Exception as exc:
        print(error(f"Could not list interfaces: {exc}"), file=sys.stderr)
        sys.exit(1)


def _iface_is_connected(iface: Any) -> bool:
    name = getattr(iface, "name", "")
    if name in ("lo", "Loopback Pseudo-Interface 1"):
        return False
    ip = getattr(iface, "ip", None)
    if not ip:
        return False
    ip_str = str(ip).strip()
    if not ip_str or ip_str.startswith("127.") or ip_str.startswith("169.254."):
        return False
    return True


def _get_default_iface() -> Any | None:
    try:
        iface_name, _, _ = scapy_conf.route.route("0.0.0.0")
        for iface in scapy_conf.ifaces.values():
            if str(iface) == str(iface_name):
                if _iface_is_connected(iface):
                    return iface
    except Exception:
        pass

    default_routes = [
        r for r in scapy_conf.route.routes if r[0] in (0, "0.0.0.0") and r[1] in (0, "0.0.0.0")
    ]
    default_routes.sort(key=lambda r: r[5])

    for route in default_routes:
        for iface in scapy_conf.ifaces.values():
            if str(iface) == str(route[3]) and _iface_is_connected(iface):
                return iface

    return None


def _resolve_iface(name_or_iface: str) -> Any:
    for iface in scapy_conf.ifaces.values():
        if iface == name_or_iface:
            return iface
    print(
        error(
            f"Interface '{name_or_iface}' not found. Use --list-interfaces to see available names."
        ),
        file=sys.stderr,
    )
    sys.exit(1)


def _ensure_routes_use_iface(iface_name: str) -> None:
    route = scapy_conf.route
    route.routes = [
        r for r in route.routes if str(r[3]) == iface_name or str(r[3]).startswith("lo")
    ]


def _check_probe_privileges() -> None:
    try:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        raw_sock.close()
    except (PermissionError, OSError):
        if sys.platform == "win32":
            msg = "Administrator privileges are required for probing. Run as Administrator."
        else:
            msg = "Raw socket access is required for probing. Run with sudo (or grant CAP_NET_RAW)."
        print(error(msg), file=sys.stderr)
        sys.exit(1)


def run(args: argparse.Namespace) -> None:
    if args.list_interfaces:
        _list_interfaces()
        sys.exit(0)

    if args.input_file is not None and args.targets:
        print(error("Cannot use both -f/--input-file and command-line targets."), file=sys.stderr)
        sys.exit(1)

    if args.input_file is None and not args.targets:
        print(
            error("No targets provided. Use -f/--input-file or specify targets directly."),
            file=sys.stderr,
        )
        sys.exit(1)

    chosen_iface: Any | None = None
    if args.iface:
        chosen_iface = _resolve_iface(args.iface)

    targets: list[str] = []
    if args.input_file is not None:
        file_targets, invalid_entries = parse_targets(args.input_file)
        for entry in invalid_entries:
            print(warning(f"Skipping invalid target from file: {entry}"))
        targets = file_targets
    else:
        for entry in args.targets:
            if is_valid_target(entry):
                targets.append(entry)
            else:
                print(warning(f"Skipping invalid target: {entry}"))

    if not targets:
        print(error("No valid targets found."), file=sys.stderr)
        sys.exit(1)

    # --- DNS resolution phase ---
    print(heading("Resolving targets"))
    resolved_ips: dict[str, str | None] = {}
    skipped: list[str] = []
    for t in targets:
        if _is_ip(t):
            resolved_ips[t] = None
            print(f"  {t}  {dim('(IP)')}")
        else:
            ip = resolve_hostname(t)
            if ip is None:
                print(f"  {warning('!')} could not resolve {t} {dim('(skipping)')}")
                skipped.append(t)
            else:
                resolved_ips[t] = ip
                print(f"  {t} -> {ip}")

    targets = [t for t in targets if t not in skipped]

    if not targets:
        print(error("No valid targets found."), file=sys.stderr)
        sys.exit(1)

    # --- Output dir / cache setup ---
    protocols = _protocol_from_arg(args.protocol)
    output_dir = Path(args.output_dir).resolve()

    if args.force:
        existing = list(output_dir.glob("*.json")) if output_dir.exists() else []
        print(f"\n{heading('Results directory')}  {dim(str(output_dir))}")
        if existing:
            target_stems = {f"{t}.json" for t in targets}
            to_overwrite = [f for f in existing if f.name in target_stems]
            print(f"  {len(to_overwrite)} result file(s) will be overwritten.")
            if not args.yes and sys.stdin.isatty():
                try:
                    answer = input("  Continue? [y/N] ").strip().lower()
                except EOFError:
                    answer = "y"
                if answer != "y":
                    print("  Aborted.")
                    sys.exit(0)
        output_dir.mkdir(parents=True, exist_ok=True)
        chown_to_invoking_user(output_dir)
        for t in targets:
            p = output_dir / f"{t}.json"
            if p.exists():
                p.unlink()
        (output_dir / ".targets").unlink(missing_ok=True)
    else:
        existing = list(output_dir.glob("*.json")) if output_dir.exists() else []
        print(f"\n{heading('Results directory')}  {dim(str(output_dir))}")
        if existing:
            print(f"  {len(existing)} existing result file(s) found.")
        output_dir.mkdir(parents=True, exist_ok=True)
        chown_to_invoking_user(output_dir)

    targets_manifest = output_dir / ".targets"
    targets_manifest.write_text("\n".join(targets) + "\n")
    chown_to_invoking_user(targets_manifest)

    # --- Cache loading phase ---
    cached_results: list[TracerouteResult] = []
    targets_to_probe: list[str] = []

    if not args.force:
        for t in targets:
            result_path = output_dir / f"{t}.json"
            if result_path.exists():
                try:
                    result = TracerouteResult.from_json(result_path)
                    if result.probing_complete:
                        result.cached = True
                        result.to_json(result_path)
                        cached_results.append(result)
                        continue
                except Exception:
                    pass
            targets_to_probe.append(t)
    else:
        targets_to_probe = list(targets)

    if cached_results:
        print(f"\n{heading('Cached')}")
        for r in cached_results:
            ip_info = f" ({r.resolved_ip})" if r.resolved_ip else ""
            unique_hops = len({h.ttl for h in r.hops})
            dest_label = green("reached") if r.destination_reached else red("not reached")
            print(f"  {r.target}{ip_info} — {unique_hops} hop(s), {dest_label} {dim('[cached]')}")

    needs_probing = len(targets_to_probe) > 0

    if not needs_probing and not cached_results:
        print(error("Nothing to do — no targets found."), file=sys.stderr)
        sys.exit(1)

    if not needs_probing:
        print(f"\nAll {len(cached_results)} target(s) cached — no probing needed.")

    # --- Interface selection ---
    if chosen_iface is None:
        chosen_iface = _get_default_iface()
    if chosen_iface is not None:
        scapy_conf.iface = chosen_iface  # type: ignore[assignment]
        _ensure_routes_use_iface(str(chosen_iface))
    else:
        print(
            warning(
                "No connected interface with a default route found. "
                "Use --list-interfaces and --iface to specify one."
            )
        )

    if needs_probing:
        _check_probe_privileges()

    if not args.no_viz:
        _launch_visualizer_background(output_dir, set(targets))

    results: list[TracerouteResult] = list(cached_results)

    # --- Probing phase ---
    if needs_probing:
        iface_label = chosen_iface.name if chosen_iface is not None else "default"
        print(f"\n{heading('Interface')}  {dim(iface_label)}")
        proto_list = ", ".join(p.value for p in protocols)
        print(f"\n{heading('Probing')}  {len(targets_to_probe)} target(s)")
        print(f"  {dim(f'protocols: {proto_list}')}")
        from src.geoip import warn_if_db_missing

        warn_if_db_missing()

        for t in targets_to_probe:
            ip = resolved_ips.get(t)
            if ip:
                print(f"  {t} -> {ip}")
            else:
                print(f"  {t}  {dim('(IP)')}")

        print()

        probe_configs = {
            t: ProbeConfig(
                target=t,
                min_ttl=args.min_ttl,
                max_ttl=args.max_ttl,
                queries=args.queries,
                port=args.port,
                timeout=args.timeout,
                wait=args.wait,
                packet_size=args.size,
                protocols=protocols,
                output_path=output_dir / f"{t}.json",
                resolved_ip=resolved_ips.get(t),
            )
            for t in targets_to_probe
        }

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_target = {
                executor.submit(trace_single_target, cfg): cfg.target
                for cfg in probe_configs.values()
            }
            for future in as_completed(future_to_target):
                target = future_to_target[future]
                try:
                    result = future.result()
                except Exception as exc:
                    print(f"  {error('!')} {target}: {exc}", file=sys.stderr)
                    continue

                if not args.no_dns:
                    resolve_result(result)
                    result.to_json(output_dir / f"{target}.json")
                    chown_to_invoking_user(output_dir / f"{target}.json")

                results.append(result)
                dest_label = green("reached") if result.destination_reached else red("not reached")
                unique_hops = len({h.ttl for h in result.hops})
                print(f"  {target} — {unique_hops} hop(s), destination {dest_label}")

    # --- Summary ---
    clear_cache()
    reached = sum(1 for r in results if r.destination_reached)
    not_reached = len(results) - reached
    parts = [f"{len(results)} result(s)"]
    if cached_results:
        parts.append(f"{len(cached_results)} cached")
    if reached:
        parts.append(f"{green(str(reached))} reached")
    if not_reached:
        parts.append(f"{red(str(not_reached))} not reached")
    print(f"\n{bold('Done.')} {' | '.join(parts)}  {dim(str(output_dir))}")

    if not args.no_viz:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print(f"\n{bold('Shutting down.')}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
