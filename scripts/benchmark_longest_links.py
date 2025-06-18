#!/usr/bin/env python3
"""Benchmark runner for TracerouteService.get_longest_links_analysis

This standalone script helps profile/compare the runtime of the longest-links
analysis against different databases or parameter sets.

Example usage:
  python scripts/benchmark_longest_links.py --db meshtastic_history_prod.db \
      --iterations 3 --min-distance 1 --min-snr -20 --max-results 100

By default it reads the database path from --db or the env var DATABASE_FILE.
It prints individual run durations and a small summary table.
"""

from __future__ import annotations

import argparse
import os
import statistics as stats
import time
from pathlib import Path

# Delay heavy imports until after we have pointed the code at the correct DB


def _parse_args() -> argparse.Namespace:  # pragma: no cover (cli helper)
    parser = argparse.ArgumentParser(description="Benchmark get_longest_links_analysis")
    parser.add_argument(
        "--db",
        dest="db_path",
        type=str,
        help="SQLite DB file to use (overrides $DATABASE_FILE)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of benchmark iterations to run",
    )
    parser.add_argument(
        "--min-distance", type=float, default=1.0, help="min_distance_km parameter"
    )
    parser.add_argument(
        "--min-snr", type=float, default=-20.0, help="min_snr parameter"
    )
    parser.add_argument(
        "--max-results", type=int, default=100, help="max_results parameter"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress detailed result output (duration only)",
    )
    return parser.parse_args()


def _print_summary(durations: list[float]):
    if not durations:
        return
    print("\nSummary (seconds):")
    print(f"  runs : {len(durations)}")
    print(f"  min  : {min(durations):.3f}")
    print(f"  max  : {max(durations):.3f}")
    print(f"  mean : {stats.mean(durations):.3f}")
    if len(durations) >= 2:
        print(f"  median: {stats.median(durations):.3f}")
    print()


def main() -> None:  # pragma: no cover (benchmark script)
    args = _parse_args()

    if args.db_path:
        db_path = Path(args.db_path).expanduser().resolve()
        if not db_path.exists():
            raise FileNotFoundError(db_path)
        os.environ["MALLA_DATABASE_FILE"] = str(db_path)
        print(f"Using database: {db_path}")
    else:
        print("Using database from $MALLA_DATABASE_FILE or default path")

    # Ensure 'src' directory is on sys.path so local imports work when run
    import sys

    ROOT_DIR = Path(__file__).resolve().parents[1]
    SRC_DIR = ROOT_DIR / "src"
    sys.path.insert(0, str(ROOT_DIR))  # allow 'import src.*'
    sys.path.insert(0, str(SRC_DIR))  # allow 'import malla.*'

    # Now that DATABASE_FILE is set, we can import the heavy modules
    from src.malla.services.traceroute_service import (
        TracerouteService,  # noqa: WPS433 (runtime import intended)
    )

    durations: list[float] = []

    for i in range(1, args.iterations + 1):
        print(f"\nRun {i}/{args.iterations} …", end=" ", flush=True)
        start = time.perf_counter()
        result = TracerouteService.get_longest_links_analysis(
            min_distance_km=args.min_distance,
            min_snr=args.min_snr,
            max_results=args.max_results,
        )
        elapsed = time.perf_counter() - start
        durations.append(elapsed)
        print(f"{elapsed:.3f}s, links: {result['summary']['total_links']}")
        if not args.quiet:
            print("  longest direct link:", result["summary"]["longest_direct"])

    _print_summary(durations)


if __name__ == "__main__":  # pragma: no cover
    main()
