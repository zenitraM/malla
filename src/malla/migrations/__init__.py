"""Startup migration framework.

Every schema or data change the capture daemon applies to the SQLite database
lives in :mod:`malla.migrations` as a named, idempotent :class:`Migration`.
Each one is tagged with a :class:`Phase` that says *when* it may run relative
to packet ingestion, which is what lets the daemon keep capturing packets while
the database is being brought up to date.

See :mod:`malla.migrations.runner` for the execution contract and
:mod:`malla.migrations.registry` for the ordered list of migrations.
"""

from __future__ import annotations

from .base import PHASE_ORDER, Migration, MigrationResult, Phase, Status, Watermark
from .registry import MIGRATIONS
from .runner import (
    MARKER_PREFIX,
    ensure_meta_table,
    forget_marker,
    marker_key,
    migration_lock,
    read_marker,
    run_migrations,
    write_marker,
)

__all__ = [
    "MARKER_PREFIX",
    "MIGRATIONS",
    "PHASE_ORDER",
    "Migration",
    "MigrationResult",
    "Phase",
    "Status",
    "Watermark",
    "ensure_meta_table",
    "forget_marker",
    "marker_key",
    "migration_lock",
    "read_marker",
    "run_migrations",
    "write_marker",
]
