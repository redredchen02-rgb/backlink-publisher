"""KeepaliveJobRegistry.start_gap_closure() subprocess-invocation contract.

No prior test exercised the gap_closure subprocess call directly (the only
existing coverage was a route-level 202/409 smoke test that fires a real
background thread). This covers the UTF-8 text-encoding fix specifically.
"""
from __future__ import annotations

__tier__ = "unit"
from unittest.mock import patch

from webui_app.services.keepalive_job import KeepaliveJobRegistry


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_start_gap_closure_passes_utf8_encoding_and_pythonioencoding_env():
    registry = KeepaliveJobRegistry()
    fake = _FakeCompleted(stdout="ok\n")

    with patch("subprocess.run", return_value=fake) as mock_run:
        job = registry.start_gap_closure()
        # start_gap_closure runs the subprocess on a background thread; give
        # it a moment to invoke subprocess.run before asserting on the call.
        for _ in range(200):
            if mock_run.call_args is not None:
                break
            import time
            time.sleep(0.01)

    assert mock_run.call_args is not None
    _args, kwargs = mock_run.call_args
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    assert job.kind == "gap_closure"
