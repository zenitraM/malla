"""In-memory hold for MQTT payloads received while the database is migrated.

The capture daemon connects to the broker *before* running the write-locking
migrations so packets published in the meantime are not lost. They queue here
(a few hundred bytes each — a few megabytes even after tens of minutes at
production rates) and are replayed through the normal ingest path once the
schema and indexes are in place.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable

logger = logging.getLogger(__name__)

#: Depth at which the buffer starts warning (the queue is only ever large when
#: a migration is unexpectedly slow, which is worth surfacing).
DEFAULT_WARN_DEPTH = 100_000


class IngestBuffer:
    """Queue of ``(topic, payload)`` pairs awaiting a writable database.

    ``append`` returns ``True`` when the payload was queued, and ``False`` when
    the caller should process it directly.

    ``drain`` is race-free: popping and the "queue is empty, stop buffering"
    decision happen under the same lock, so a payload delivered concurrently
    either lands in the queue (and is drained) or goes straight through — never
    both, never neither.
    """

    def __init__(
        self,
        *,
        warn_depth: int = DEFAULT_WARN_DEPTH,
        max_depth: int | None = None,
    ) -> None:
        self._items: deque[tuple[str, bytes]] = deque()
        self._lock = threading.Lock()
        self._buffering = False
        self._warn_depth = warn_depth
        self._max_depth = max_depth
        self._dropped = 0
        self._warned = False

    @property
    def buffering(self) -> bool:
        """Whether ``append`` currently queues instead of processing."""
        with self._lock:
            return self._buffering

    @property
    def depth(self) -> int:
        """Number of queued payloads."""
        with self._lock:
            return len(self._items)

    @property
    def dropped(self) -> int:
        """Payloads dropped because the buffer hit ``max_depth``."""
        with self._lock:
            return self._dropped

    def start(self) -> None:
        """Begin queuing payloads."""
        with self._lock:
            self._buffering = True
            self._warned = False

    def stop(self) -> None:
        """Stop queuing (payloads already queued stay until drained)."""
        with self._lock:
            self._buffering = False

    def append(self, topic: str, payload: bytes) -> bool:
        """Queue one payload, or return ``False`` if the caller should handle it."""
        with self._lock:
            if not self._buffering:
                return False
            if self._max_depth is not None and len(self._items) >= self._max_depth:
                self._dropped += 1
                if self._dropped % 10_000 == 1:
                    logger.error(
                        "Ingest buffer full (%s payloads, %s dropped while migrating)",
                        self._max_depth,
                        self._dropped,
                    )
                return True
            self._items.append((topic, payload))
            depth = len(self._items)
            if depth >= self._warn_depth and not self._warned:
                self._warned = True
                logger.warning(
                    "Ingest buffer holds %s payloads; a migration is taking a long time",
                    depth,
                )
            return True

    def drain(self, process: Callable[[str, bytes], None]) -> int:
        """Replay every queued payload through *process*, then stop buffering.

        Returns the number of payloads processed. ``process`` runs outside the
        lock, so the MQTT callback can keep queuing meanwhile.
        """
        processed = 0
        while True:
            with self._lock:
                if not self._items:
                    self._buffering = False
                    return processed
                topic, payload = self._items.popleft()
            try:
                process(topic, payload)
            except Exception:  # noqa: BLE001 - one bad packet must not stall the drain
                logger.exception("Failed to process buffered packet on %s", topic)
            processed += 1
