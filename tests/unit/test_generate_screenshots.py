import socket
import sqlite3
from pathlib import Path

from scripts import generate_screenshots as gs


def test_find_free_port():
    """_find_free_port should return a port that is immediately available."""

    port = gs._find_free_port()
    assert isinstance(port, int) and 0 < port < 65536

    # The port should be free to bind to – try binding and releasing
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))


def test_build_demo_database(tmp_path):
    """Verify that a demo database is created with expected tables."""

    db_file = Path(tmp_path) / "demo.db"
    gs._build_demo_database(db_file)

    assert db_file.exists() and db_file.stat().st_size > 0, "Demo DB was not created"

    with sqlite3.connect(db_file) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='packet_history'"
        )
        assert cursor.fetchone(), "packet_history table missing"
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='node_info'"
        )
        assert cursor.fetchone(), "node_info table missing"
