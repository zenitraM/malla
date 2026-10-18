"""Tests for the in-memory ingest buffer used during startup migrations."""

import threading

from malla.ingest_buffer import IngestBuffer


def test_append_returns_false_until_started():
    buffer = IngestBuffer()

    assert buffer.buffering is False
    assert buffer.append("msh/x", b"payload") is False

    buffer.start()
    assert buffer.buffering is True
    assert buffer.append("msh/x", b"payload") is True
    assert buffer.depth == 1


def test_drain_replays_in_order_and_stops_buffering():
    buffer = IngestBuffer()
    buffer.start()
    for index in range(5):
        buffer.append("msh/x", str(index).encode())

    seen: list[bytes] = []
    drained = buffer.drain(lambda topic, payload: seen.append(payload))

    assert drained == 5
    assert seen == [b"0", b"1", b"2", b"3", b"4"]
    assert buffer.buffering is False
    assert buffer.depth == 0
    # After the drain, callers process payloads directly.
    assert buffer.append("msh/x", b"later") is False


def test_drain_keeps_buffered_payloads_when_a_replay_fails():
    buffer = IngestBuffer()
    buffer.start()
    buffer.append("msh/x", b"boom")
    buffer.append("msh/x", b"fine")

    seen: list[bytes] = []

    def process(_topic: str, payload: bytes) -> None:
        if payload == b"boom":
            raise ValueError("bad packet")
        seen.append(payload)

    drained = buffer.drain(process)

    assert drained == 2
    assert seen == [b"fine"]
    assert buffer.buffering is False


def test_no_payload_is_lost_when_appenders_race_the_drain():
    """Packets either queue (and are drained) or go straight through — never both."""

    buffer = IngestBuffer()
    buffer.start()
    processed: list[bytes] = []
    lock = threading.Lock()
    total_per_thread = 200
    threads = 4

    def record(_topic: str, payload: bytes) -> None:
        with lock:
            processed.append(payload)

    def worker(worker_id: int) -> None:
        for index in range(total_per_thread):
            payload = f"{worker_id}-{index}".encode()
            if not buffer.append("msh/x", payload):
                record("msh/x", payload)  # append refused: handle it directly

    workers = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for thread in workers:
        thread.start()

    # Drain while the producers are still running.
    buffer.drain(record)
    for thread in workers:
        thread.join()

    total = threads * total_per_thread
    assert buffer.buffering is False
    assert buffer.depth == 0
    assert len(processed) == total
    assert len(set(processed)) == total


def test_depth_warning_and_max_depth_drops():
    buffer = IngestBuffer(warn_depth=2, max_depth=3)
    buffer.start()
    for index in range(5):
        buffer.append("msh/x", str(index).encode())

    assert buffer.depth == 3
    assert buffer.dropped == 2

    seen: list[bytes] = []
    buffer.drain(lambda topic, payload: seen.append(payload))
    assert seen == [b"0", b"1", b"2"]
