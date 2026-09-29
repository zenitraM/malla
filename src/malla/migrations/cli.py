"""``malla-migrate``: inspect or apply the database migrations by hand.

Normally the capture daemon applies every pending migration on startup. The CLI
exists for operators who want to see what would run, run it without starting
MQTT (a web-only deployment, or a maintenance window), or clear a progress marker
so a migration runs again::

    malla-migrate --list
    malla-migrate --dry-run
    malla-migrate --phase derived
    malla-migrate --forget primary_channel_backfill
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time

from ..config import get_config
from .base import PHASE_ORDER, Migration, Phase, Status
from .registry import MIGRATIONS
from .runner import forget_marker, read_marker, run_migrations

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="malla-migrate",
        description="Apply pending database migrations (the capture daemon does this on startup).",
    )
    parser.add_argument(
        "--database", default=None, help="override the configured database file"
    )
    parser.add_argument(
        "--phase",
        action="append",
        choices=[phase.value for phase in PHASE_ORDER],
        help="only run migrations of this phase (repeatable)",
    )
    parser.add_argument("--list", action="store_true", help="show migrations and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would run, change nothing"
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit non-zero on the first failure"
    )
    parser.add_argument(
        "--forget",
        action="append",
        default=[],
        metavar="NAME",
        help="clear the progress marker of NAME so it runs again (repeatable)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser


def _describe(conn: sqlite3.Connection, migration: Migration) -> str:
    recorded, watermark = read_marker(conn, migration.name)
    state = "applied" if recorded else "never run"
    if watermark:
        state = f"{state} (watermark {watermark})"
    try:
        pending = migration.pending(conn, watermark)
    except Exception as exc:  # noqa: BLE001 - inspection must not fail the command
        return (
            f"{migration.name}  [{migration.phase.value}]  {state}  check failed: {exc}"
        )
    if pending:
        state = f"{state}, work pending"
    return f"{migration.name}  [{migration.phase.value}]  {state}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    db_path = args.database or get_config().database_file

    if args.list:
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
        except sqlite3.Error as exc:
            print(f"cannot open {db_path}: {exc}", file=sys.stderr)
            return 2
        try:
            for migration in MIGRATIONS:
                print(_describe(conn, migration))
        finally:
            conn.close()
        return 0

    phases: list[Phase] | None = [Phase(p) for p in args.phase] if args.phase else None

    conn = sqlite3.connect(db_path, timeout=30)
    try:
        for name in args.forget:
            if forget_marker(conn, name):
                print(f"forgot progress marker of {name}")
            else:
                print(f"no progress marker for {name}")
        conn.commit()

        started = time.monotonic()
        results = run_migrations(
            conn,
            MIGRATIONS,
            phases=phases,
            strict=args.strict,
            dry_run=args.dry_run,
        )
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    applied = [r for r in results if r.status is Status.APPLIED]
    failed = [r for r in results if r.status is Status.FAILED]
    skipped = [r for r in results if r.status is Status.SKIPPED]
    for result in results:
        if result.status is not Status.SKIPPED:
            print(result.describe())
    print(
        f"{len(applied)} applied, {len(skipped)} up to date, {len(failed)} failed "
        f"in {time.monotonic() - started:.2f}s ({db_path})"
    )
    for result in failed:
        print(f"failed: {result.name}: {result.detail}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
