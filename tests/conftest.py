"""Every test is offline. This file runs before any test module is imported.

1. Fake credentials go into the environment before `config` is imported, so the real .env is
   never used by a test (the same values tests/test_all.py sets).
2. No test may reach the network: a connection to anything but this machine raises.
3. Reports, the cache and the jobs database go to a temporary folder.
"""
import os
import socket

os.environ.update({
    "NICRRON_API_KEY": "nk-FAKE-offline-0000aaaa1111bbbb",
    "PRISMTRACE_API_KEY": "pt-sk-FAKE-offline-2222cccc3333dddd",
    "PRISMTRACE_PROJECT_ID": "00000000-0000-0000-0000-000000000000",
    "PRISM_HIDE_SYSTEM_PROMPT": "true",
    "PRISM_MAX_CHARS": "500",
    "PRISM_SEND_LATENCY": "false",
    "PRISM_ENABLED": "true",
    "MASSIVE_API_KEY": "mk-FAKE-offline-4444eeee5555ffff",
    "SEC_USER_AGENT": "Offline Tests offline@example.invalid",
    "SOURCE_MODE": "replay",
})

import pytest  # noqa: E402

_LOCAL = {"127.0.0.1", "::1", "localhost"}
_real_connect = socket.socket.connect


def _offline_connect(self, address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in _LOCAL and not host.startswith("/"):
        raise OSError(f"tests are offline: refused a connection to {host!r}")
    return _real_connect(self, address, *args, **kwargs)


socket.socket.connect = _offline_connect


@pytest.fixture(autouse=True)
def _temporary_output(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    yield
