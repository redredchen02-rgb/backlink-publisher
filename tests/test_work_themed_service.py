"""Flask-free unit tests for webui_app.services.work_themed_service (U6).

No Flask app context required.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import pytest

from webui_app.services import work_themed_service as svc


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset in-memory run registry between tests."""
    svc._RUNS.clear()
    yield
    svc._RUNS.clear()


# ── parse_lines ───────────────────────────────────────────────────────────────

class TestParseLines:
    def test_empty_string_returns_empty(self):
        assert svc.parse_lines("") == []

    def test_none_like_empty_returns_empty(self):
        assert svc.parse_lines("") == []

    def test_strips_whitespace(self):
        assert svc.parse_lines("  a  \n  b  ") == ["a", "b"]

    def test_skips_blank_lines(self):
        assert svc.parse_lines("a\n\n\nb") == ["a", "b"]

    def test_single_line(self):
        assert svc.parse_lines("https://example.com") == ["https://example.com"]


# ── parse_plan_output ─────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, main_url="https://main.com"):
        self.main_url = main_url


class TestParsePlanOutput:
    def _jsonl(self, *rows):
        return "\n".join(json.dumps(r) for r in rows) + "\n"

    def test_extracts_seo_canonical_url(self):
        stdout = self._jsonl(
            {"seo": {"canonical_url": "https://work.com/page1"}, "title": "T"}
        )
        rows = svc.parse_plan_output(stdout, _FakeEntry())
        assert rows == [{"work_url": "https://work.com/page1", "status": "success"}]

    def test_falls_back_to_url_field(self):
        stdout = self._jsonl({"url": "https://work.com/page2"})
        rows = svc.parse_plan_output(stdout, _FakeEntry())
        assert rows == [{"work_url": "https://work.com/page2", "status": "success"}]

    def test_deduplicates_canonical(self):
        stdout = self._jsonl(
            {"seo": {"canonical_url": "https://work.com/dup"}},
            {"seo": {"canonical_url": "https://work.com/dup"}},
        )
        rows = svc.parse_plan_output(stdout, _FakeEntry())
        assert len(rows) == 1

    def test_skips_invalid_json_lines(self):
        stdout = "NOT JSON\n" + json.dumps({"url": "https://work.com/ok"}) + "\n"
        rows = svc.parse_plan_output(stdout, _FakeEntry())
        assert len(rows) == 1
        assert rows[0]["work_url"] == "https://work.com/ok"

    def test_empty_stdout_returns_empty(self):
        assert svc.parse_plan_output("", _FakeEntry()) == []

    def test_rows_with_no_url_skipped(self):
        stdout = self._jsonl({"title": "no url here"})
        assert svc.parse_plan_output(stdout, _FakeEntry()) == []


# ── register_run / get_run ────────────────────────────────────────────────────

class TestRunRegistry:
    def test_register_and_get(self):
        svc.register_run("run-001", "https://main.com", {"total": 3}, [])
        run = svc.get_run("run-001")
        assert run is not None
        assert run["main_url"] == "https://main.com"
        assert run["summary"] == {"total": 3}

    def test_get_unknown_run_returns_none(self):
        assert svc.get_run("nonexistent") is None

    def test_evicts_oldest_when_over_cap(self):
        old_max = svc._MAX_RUNS
        svc._MAX_RUNS = 3
        try:
            for i in range(4):
                svc.register_run(f"run-{i:03d}", "https://m.com", {}, [])
            assert "run-000" not in svc._RUNS
            assert "run-003" in svc._RUNS
            assert len(svc._RUNS) == 3
        finally:
            svc._MAX_RUNS = old_max

    def test_update_existing_run(self):
        svc.register_run("run-001", "https://m.com", {"total": 1}, [])
        svc.register_run("run-001", "https://m.com", {"total": 2}, [])
        assert svc.get_run("run-001")["summary"]["total"] == 2
