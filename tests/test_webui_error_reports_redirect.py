"""Contract tests for the top-level /error-reports → SPA redirect routes.

``routes/command_center.py::error_reports_redirect`` mirrors the legacy→SPA
redirect pattern used by equity_ledger / keep_alive / pr_queue: the bare
``/error-reports`` path (linked from the command-center card) and its
``/<report_id>`` detail variant both 302 to the SPA dashboard under
``/app/error-reports``.
"""
from __future__ import annotations


class TestErrorReportsRedirect:
    def test_get_error_reports_redirects_to_spa(self, client):
        resp = client.get("/error-reports")
        assert resp.status_code == 302
        assert "/app/error-reports" in resp.location

    def test_get_error_report_detail_redirects_to_spa(self, client):
        resp = client.get("/error-reports/rep-123")
        assert resp.status_code == 302
        assert "/app/error-reports/rep-123" in resp.location
