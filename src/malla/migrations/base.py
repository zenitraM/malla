"""Core types for the startup migration framework.

A migration is a named, idempotent step. Its *phase* says when it may run
relative to packet ingestion:

``SCHEMA``
    Cheap DDL (tables, columns). Re-checked on every run; must complete before
    the first row is written.
``BLOCKING``
    DDL that takes SQLite's write lock (index builds on large tables). No
    concurrent writes, so the capture buffers packets while these run.
``DERIVED``
    Data work that only touches already-committed rows. Safe in the background
    while packets are ingested.

Two independent ways a migration can report "already done":

* structural migrations re-check the database on every run (``pending`` looks at
  ``sqlite_master`` / ``PRAGMA table_info``), so adding a column or index to the
  registry keeps working for databases that already ran the migration once;
* data migrations record a *watermark* in ``malla_meta`` under
  ``migration:<name>`` and default to running exactly once.

Every ``apply`` must be safe to run twice over the same window: the marker is
written after the work, so a crash in between repeats the migration on the next
start.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class Phase(StrEnum):
    """When a migration is allowed to run relative to packet ingestion."""

    SCHEMA = "schema"
    BLOCKING = "blocking"
    DERIVED = "derived"


PHASE_ORDER: tuple[Phase, ...] = (Phase.SCHEMA, Phase.BLOCKING, Phase.DERIVED)

PHASE_DESCRIPTION: dict[Phase, str] = {
    Phase.SCHEMA: "cheap DDL (tables, columns) before the first write",
    Phase.BLOCKING: "write-locking DDL (index builds); ingestion is paused",
    Phase.DERIVED: "idempotent data work; safe while packets are ingested",
}

#: Opaque, migration-owned progress marker. ``None`` means "never recorded";
#: an empty string means "recorded, nothing to track" (one-shot migrations).
Watermark = str | None


class Status(StrEnum):
    """Outcome of one migration run."""

    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"


def _one_shot(_conn: sqlite3.Connection, watermark: Watermark) -> bool:
    """Default :attr:`Migration.pending`: run once, then never again."""
    return watermark is None


@dataclass(frozen=True)
class Migration:
    """One named, idempotent database change.

    ``apply`` receives the connection and the stored watermark and returns the
    new watermark (``None`` when the migration has no progress to track).
    ``pending`` must be read-only and say whether there is still work to do.
    """

    name: str
    phase: Phase
    apply: Callable[[sqlite3.Connection, Watermark], Watermark]
    description: str = ""
    pending: Callable[[sqlite3.Connection, Watermark], bool] = _one_shot


@dataclass
class MigrationResult:
    """What happened to one migration."""

    name: str
    phase: Phase
    status: Status
    watermark: Watermark = None
    detail: str = ""
    seconds: float = 0.0
    fields: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        extra = f" ({self.detail})" if self.detail else ""
        return f"{self.name} [{self.phase.value}] {self.status.value}{extra} in {self.seconds:.2f}s"
