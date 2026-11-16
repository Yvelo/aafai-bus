import os
from unittest.mock import patch

from src.server import _acquire_scheduler_lock
import src.server as server


def test_scheduler_lock_is_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_scheduler_lock_handle", None)
    lock_path = tmp_path / "aafai-bus-scheduler.lock"

    with patch("src.server.tempfile.gettempdir", return_value=str(tmp_path)):
        assert _acquire_scheduler_lock() is True
        first = server._scheduler_lock_handle

        monkeypatch.setattr(server, "_scheduler_lock_handle", None)
        assert _acquire_scheduler_lock() is False

    first.close()
    server._scheduler_lock_handle = None
    os.remove(lock_path)
