"""Fail accidental network connections, including local Ollama, during pytest."""
import socket
from unittest.mock import patch


def pytest_configure(config):
    # Active during test collection as well as test execution.
    blocker = patch.object(
        socket.socket, "connect",
        side_effect=AssertionError("Network disabled: mock all provider calls"),
    )
    blocker.start()
    config.add_cleanup(blocker.stop)
