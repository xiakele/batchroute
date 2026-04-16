from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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
from src.parser import parse_targets
from src.prober import ProbeConfig, trace_single_target
from src.resolver import clear_cache, resolve_result


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="batchroute",
        description="Batch traceroute tool with topology visualization.",
    )

    p.add_argument(
        "-f",
        "--input-file",
        required=True,
        help="Path to a .txt or .csv file containing target IP addresses.",
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

    return p


def _protocol_from_arg(val: str | None) -> list[Protocol]:
    if val is None:
        return list(ALL_PROTOCOLS)
    return [Protocol(val)]


def _start_visualizer(results_dir: str) -> None:
    from visualizer.app import create_app

    app = create_app(results_dir=results_dir)
    app.run(host="0.0.0.0", port=8050, debug=False, use_reloader=False)


def _launch_visualizer_background(results_dir: Path) -> None:
    thread = threading.Thread(target=_start_visualizer, args=(str(results_dir),), daemon=True)
    thread.start()
    time.sleep(1.5)
    print("Visualizer running at http://localhost:8050 — press Ctrl+C to exit.")
    webbrowser.open("http://localhost:8050")


def run(args: argparse.Namespace) -> None:
    targets = parse_targets(args.input_file)
    if not targets:
        print("No valid IP addresses found in input file.", file=sys.stderr)
        sys.exit(1)

    protocols = _protocol_from_arg(args.protocol)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_viz:
        _launch_visualizer_background(output_dir)

    proto_list = ", ".join(p.value for p in protocols)
    print(f"Probing {len(targets)} target(s) with protocol(s): {proto_list}")

    results: list[TracerouteResult] = []
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
        )
        for t in targets
    }

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_target = {
            executor.submit(trace_single_target, cfg): cfg.target for cfg in probe_configs.values()
        }
        for future in as_completed(future_to_target):
            target = future_to_target[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f"Error probing {target}: {exc}", file=sys.stderr)
                continue

            if not args.no_dns:
                resolve_result(result)
                result.to_json(output_dir / f"{target}.json")

            results.append(result)
            dest = "reached" if result.destination_reached else "not reached"
            print(f"  {target} — {len(result.hops)} hop(s), destination {dest}")

    clear_cache()
    print(f"Probing complete. {len(results)} result(s) written to {output_dir}/")

    if not args.no_viz:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nShutting down.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
