"""The ordered list of migrations the capture daemon applies.

Order inside a phase is the order here; phases always run one after another
(see :data:`malla.migrations.base.PHASE_ORDER`). Adding a migration means
appending it here — never reordering existing entries, and never renaming one
that has already shipped (its name is the progress key in ``malla_meta``).
"""

from __future__ import annotations

from .base import Migration
from .derived import DERIVED_MIGRATIONS
from .structural import BLOCKING_MIGRATIONS, SCHEMA_MIGRATIONS

MIGRATIONS: tuple[Migration, ...] = (
    *SCHEMA_MIGRATIONS,
    *BLOCKING_MIGRATIONS,
    *DERIVED_MIGRATIONS,
)

__all__ = ["MIGRATIONS"]
