#!/usr/bin/env python3
"""Create a demo SQLite database populated with Meshworks fixtures.

This helper is handy for local UI testing when no live Meshtastic capture
is available.  By default it drops a database alongside this script under the
name ``meshtastic_demo.db`` but you can point it anywhere via ``--output``.

Usage
-----
```bash
python -m uv run python scripts/create_demo_database.py --output ./meshtastic_history.db
```
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.fixtures.database_fixtures import DatabaseFixtures  # noqa: E402


def build_demo_database(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    fixtures = DatabaseFixtures()
    fixtures.create_test_database(str(path))
    print(f"✅ Demo database created at {path} (size: {path.stat().st_size} bytes)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=ROOT / "meshtastic_demo.db",
        help="Where to write the demo database (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    build_demo_database(args.output)


if __name__ == "__main__":
    main()
