"""Explicit, resumable preparation of stored traceroute packets."""

import argparse
import json
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from .database.traceroute_schema import TRACEROUTE_PREDICATE, ensure_traceroute_schema
from .database.traceroutes import (
    PARSER_VERSION,
    inspect_traceroutes,
    write_traceroute,
)


def prepare_traceroutes(
    conn: sqlite3.Connection,
    batch_size: int = 1000,
    progress: Callable[[int], None] | None = None,
) -> dict:
    """Fill missing/pending/older-version records, then validate under a write lock.

    Each batch commits independently. An ID boundary keeps continuous capture
    from extending the run indefinitely; captures beyond it use the same writer.
    Final validation includes any raw-only imports that arrived during the run.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        ensure_traceroute_schema(cursor)
        # Building this raw-history index is explicit maintenance work, never
        # part of web/capture startup. It also speeds subsequent resumptions.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_packet_history_traceroute_id "
            f"ON packet_history(id) WHERE {TRACEROUTE_PREDICATE}"
        )
        if cursor.execute(
            "SELECT 1 FROM traceroute_routes WHERE parser_version > ? LIMIT 1",
            (PARSER_VERSION,),
        ).fetchone():
            raise ValueError("Database uses a newer traceroute decoder; upgrade Malla")
        upper_id = cursor.execute(
            "SELECT COALESCE(MAX(id), 0) FROM packet_history"
        ).fetchone()[0]

    last_id = None
    processed = 0
    while True:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            lower_bound = "" if last_id is None else "AND id > ?"
            params = [upper_id]
            if last_id is not None:
                params.append(last_id)
            rows = cursor.execute(
                f"""
                SELECT id, timestamp, mesh_packet_id, from_node_id, to_node_id,
                       hop_start, hop_limit, channel_id, raw_payload
                FROM packet_history
                WHERE {TRACEROUTE_PREDICATE} AND id <= ? {lower_bound}
                    AND NOT EXISTS (
                        SELECT 1 FROM traceroute_routes
                        WHERE packet_id = packet_history.id AND parser_version = ?
                    )
                ORDER BY id LIMIT ?
                """,
                [*params, PARSER_VERSION, batch_size],
            ).fetchall()
            if not rows:
                break
            for row in rows:
                write_traceroute(cursor, dict(row))
            last_id = rows[-1]["id"]
        processed += len(rows)
        if progress is not None:
            progress(processed)

    with conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()
        result = inspect_traceroutes(cursor)
    return {**result, "processed_this_run": processed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", required=True, type=Path, help="Existing database path"
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000, help="Packets per transaction"
    )
    parser.add_argument(
        "--check",
        "--dry-run",
        action="store_true",
        help="Report counts without modifying the database",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    path = args.database.expanduser().resolve()
    print(f"Database: {path}", flush=True)
    try:
        # mode=rw refuses to create a database for a misspelled path. Neither
        # configuration defaults nor capture startup participate in this command.
        mode = "ro" if args.check else "rw"
        with closing(
            sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=30.0)
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            if args.check:
                with conn:
                    conn.execute("BEGIN")
                    result = inspect_traceroutes(conn.cursor())
            else:
                result = prepare_traceroutes(
                    conn,
                    batch_size=args.batch_size,
                    progress=lambda count: print(
                        f"Prepared {count} traceroutes", flush=True
                    ),
                )
        print(json.dumps(result, indent=2), flush=True)
        return 0 if result["complete"] else 1
    except KeyboardInterrupt:
        print(
            "Interrupted. Committed batches are safe; run the same command to resume.",
            file=sys.stderr,
        )
        return 130
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"Traceroute preparation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
