"""Tests for ErrorReportSqliteStore (Unit 2) — error_reports -> webui.db
``error_reports`` table.

Verifies add()/get()/list() roundtrip, targeted update_status()/
attach_description() mutation (paired assertions -- only the intended field
changes), status/severity/source/fingerprint/time-range filtering, empty-store
list(), restart persistence (fresh WebUIDatabase instance against the same
file), find_by_fingerprint()/increment_occurrence(), delete(), Store protocol
compliance, and -- the load-bearing constraint of this unit -- that add() is a
real single-row INSERT that loses no rows under concurrent callers (proven via
threads, not just asserted in the docstring).

Plan: docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md Unit 2.
"""

from __future__ import annotations

__tier__ = "integration"

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from webui_store.base import Store
from webui_store.error_reports import ErrorReportSqliteStore, STATUS_VALUES
from webui_store.sqlite_base import WebUIDatabase


def _store(tmp_path: Path) -> ErrorReportSqliteStore:
    return ErrorReportSqliteStore(WebUIDatabase(tmp_path / "webui.db"))


def _report(**overrides: object) -> dict:
    base: dict = {
        "message": "TypeError: x is not a function",
        "stack": "at foo (app.js:1:1)",
        "url": "https://example.test/app/publish",
        "source": "vue",
        "severity": "error",
        "fingerprint": "fp-abc123",
    }
    base.update(overrides)
    return base


# ── Store protocol ──────────────────────────────────────────────────────────

class TestStoreProtocol:
    def test_isinstance_store(self, tmp_path):
        assert isinstance(_store(tmp_path), Store)

    def test_status_values_is_the_canonical_three_state_vocabulary(self, tmp_path):
        # Locks in the closed set Unit 3's PATCH schema / Unit 8's filter UI
        # must both read from here rather than re-inventing their own list.
        assert STATUS_VALUES == {"open", "acknowledged", "resolved"}

    def test_save_raises_not_implemented(self, tmp_path):
        # Hard constraint from the plan: this store must never support a
        # whole-table overwrite. Proven here, not just asserted in a
        # docstring -- mirrors BatchOpsSqliteStore.save()'s identical choice.
        store = _store(tmp_path)
        with pytest.raises(NotImplementedError):
            store.save([])


# ── add() / get() / list() ───────────────────────────────────────────────────

class TestAddGetList:
    def test_add_then_get_matches_and_list_includes_it(self, tmp_path):
        store = _store(tmp_path)
        report_id = store.add(_report(message="boom"))

        got = store.get(report_id)
        assert got is not None
        assert got["id"] == report_id
        assert got["message"] == "boom"
        assert got["status"] == "open"
        assert got["occurrences"] == 1

        listed = store.list()
        assert [r["id"] for r in listed] == [report_id]

    def test_list_on_empty_store_returns_empty_list(self, tmp_path):
        assert _store(tmp_path).list() == []

    def test_load_on_empty_store_returns_empty_list(self, tmp_path):
        # Store protocol: load() must not error on an absent/empty table.
        assert _store(tmp_path).load() == []

    def test_get_nonexistent_returns_none(self, tmp_path):
        assert _store(tmp_path).get("no-such-id") is None

    def test_add_defaults_status_to_open(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report())
        assert store.get(rid)["status"] == "open"

    def test_add_ignores_caller_supplied_id_and_occurrences(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report(id="caller-supplied", occurrences=999))
        assert rid != "caller-supplied"
        got = store.get(rid)
        assert got["id"] == rid
        assert got["occurrences"] == 1

    def test_add_invalid_status_raises(self, tmp_path):
        store = _store(tmp_path)
        with pytest.raises(ValueError, match="status must be one of"):
            store.add(_report(status="bogus"))


# ── update_status() ──────────────────────────────────────────────────────────

class TestUpdateStatus:
    def test_updates_only_status_field(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report(message="keep-me", severity="warning"))
        before = store.get(rid)

        assert store.update_status(rid, "resolved") is True
        after = store.get(rid)

        assert after["status"] == "resolved"
        # Paired assertion: status changed, everything else did not.
        assert after["message"] == before["message"]
        assert after["severity"] == before["severity"]
        assert after["fingerprint"] == before["fingerprint"]
        assert after["occurrences"] == before["occurrences"]
        assert after["created_at"] == before["created_at"]

    def test_invalid_status_raises(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report())
        with pytest.raises(ValueError, match="status must be one of"):
            store.update_status(rid, "bogus")

    def test_nonexistent_id_returns_false(self, tmp_path):
        assert _store(tmp_path).update_status("no-such-id", "resolved") is False


# ── attach_description() ─────────────────────────────────────────────────────

class TestAttachDescription:
    def test_attach_description_sets_field_others_unchanged(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report(message="keep-me"))
        before = store.get(rid)

        assert store.attach_description(rid, "Happened after clicking Save") is True
        after = store.get(rid)

        assert after["user_description"] == "Happened after clicking Save"
        # Paired assertion: description added, everything else untouched.
        assert after["message"] == before["message"]
        assert after["status"] == before["status"]
        assert after["fingerprint"] == before["fingerprint"]

    def test_nonexistent_id_returns_false(self, tmp_path):
        assert _store(tmp_path).attach_description("no-such-id", "text") is False


# ── list(filters=...) ────────────────────────────────────────────────────────

class TestListFilters:
    def test_status_filter_excludes_unresolved_includes_resolved(self, tmp_path):
        store = _store(tmp_path)
        open_id = store.add(_report(fingerprint="fp-open"))
        resolved_id = store.add(_report(fingerprint="fp-resolved"))
        store.update_status(resolved_id, "resolved")

        resolved_list = store.list(filters={"status": "resolved"})
        ids = {r["id"] for r in resolved_list}

        assert resolved_id in ids       # positive
        assert open_id not in ids       # negative, paired with the positive

    def test_severity_source_fingerprint_exact_match(self, tmp_path):
        store = _store(tmp_path)
        target = store.add(
            _report(severity="critical", source="legacy-js", fingerprint="fp-x")
        )
        other = store.add(
            _report(severity="warning", source="vue", fingerprint="fp-y")
        )

        assert [r["id"] for r in store.list(filters={"severity": "critical"})] == [target]
        assert [r["id"] for r in store.list(filters={"source": "legacy-js"})] == [target]
        assert [r["id"] for r in store.list(filters={"fingerprint": "fp-x"})] == [target]
        # Paired: the other report is excluded by each of the filters above.
        assert other not in {r["id"] for r in store.list(filters={"fingerprint": "fp-x"})}

    def test_time_range_filter(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report())
        created_at = store.get(rid)["created_at"]

        assert [r["id"] for r in store.list(filters={"since": created_at})] == [rid]
        assert [r["id"] for r in store.list(filters={"until": created_at})] == [rid]
        # Negative: a since-bound far in the future matches nothing.
        assert store.list(filters={"since": "9999-01-01T00:00:00+00:00"}) == []

    def test_list_no_filters_returns_everything_newest_first(self, tmp_path):
        import time

        store = _store(tmp_path)
        first = store.add(_report(fingerprint="fp-1"))
        # created_at has no secondary tiebreaker (matches CampaignSqliteStore's
        # ORDER BY created_at DESC convention) -- sleep to avoid a same-instant
        # tie, exactly like test_webui_store_campaign_sqlite.py's
        # test_sorted_created_at_desc does.
        time.sleep(0.01)
        second = store.add(_report(fingerprint="fp-2"))
        assert [r["id"] for r in store.list()] == [second, first]


# ── find_by_fingerprint() / increment_occurrence() ──────────────────────────

class TestFingerprintAndOccurrence:
    def test_find_by_fingerprint_matches_and_increment_bumps_only_count_and_seen(
        self, tmp_path
    ):
        store = _store(tmp_path)
        rid = store.add(_report(fingerprint="fp-dup", message="same bug"))
        before = store.get(rid)

        found = store.find_by_fingerprint("fp-dup")
        assert found is not None
        assert found["id"] == rid

        assert store.increment_occurrence(rid) is True
        after = store.get(rid)

        assert after["occurrences"] == before["occurrences"] + 1
        assert after["last_seen_at"] >= before["last_seen_at"]
        # Paired assertion: only occurrences + last_seen_at changed.
        assert after["message"] == before["message"]
        assert after["status"] == before["status"]
        assert after["fingerprint"] == before["fingerprint"]
        assert after["updated_at"] == before["updated_at"]

    def test_find_by_fingerprint_nonexistent_returns_none(self, tmp_path):
        store = _store(tmp_path)
        store.add(_report(fingerprint="fp-real"))
        assert store.find_by_fingerprint("fp-does-not-exist") is None

    def test_find_by_fingerprint_falsy_returns_none_without_matching_anything(
        self, tmp_path
    ):
        store = _store(tmp_path)
        store.add(_report(fingerprint="fp-real"))
        assert store.find_by_fingerprint(None) is None
        assert store.find_by_fingerprint("") is None

    def test_find_by_fingerprint_matches_resolved_reports_too(self, tmp_path):
        # Deliberate design decision (see module docstring): find_by_fingerprint
        # is status-agnostic. The open-vs-resolved merge *policy* is the
        # endpoint layer's job, not persistence's -- lock that in here so a
        # future refactor can't silently flip it either way unnoticed.
        store = _store(tmp_path)
        rid = store.add(_report(fingerprint="fp-closed"))
        store.update_status(rid, "resolved")

        found = store.find_by_fingerprint("fp-closed")
        assert found is not None
        assert found["id"] == rid
        assert found["status"] == "resolved"

    def test_increment_occurrence_nonexistent_returns_false(self, tmp_path):
        assert _store(tmp_path).increment_occurrence("no-such-id") is False


# ── delete() ──────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_removes_report(self, tmp_path):
        store = _store(tmp_path)
        rid = store.add(_report(fingerprint="fp-victim"))
        other_id = store.add(_report(fingerprint="fp-other"))

        assert store.delete(rid) is True
        assert store.get(rid) is None
        remaining_ids = {r["id"] for r in store.list()}
        assert rid not in remaining_ids
        assert other_id in remaining_ids  # paired: unrelated row survives

    def test_delete_nonexistent_id_does_not_raise(self, tmp_path):
        assert _store(tmp_path).delete("no-such-id") is False


# ── Integration: restart persistence ────────────────────────────────────────

class TestRestartPersistence:
    def test_reports_survive_fresh_webuidatabase_instance(self, tmp_path):
        db_path = tmp_path / "webui.db"
        store1 = ErrorReportSqliteStore(WebUIDatabase(db_path))
        rid = store1.add(_report(message="pre-restart"))

        # Simulate a process restart: a brand new WebUIDatabase + store
        # instance constructed against the same on-disk file.
        store2 = ErrorReportSqliteStore(WebUIDatabase(db_path))
        got = store2.get(rid)

        assert got is not None
        assert got["message"] == "pre-restart"
        assert [r["id"] for r in store2.list()] == [rid]


# ── Integration: concurrent add() ───────────────────────────────────────────

class TestConcurrentAdd:
    def test_concurrent_add_shared_instance_loses_no_rows(self, tmp_path):
        # Realistic production shape: one running WebUI process, one
        # lazily-constructed singleton store instance, many browser tabs
        # POSTing concurrently.
        store = _store(tmp_path)
        n = 30

        def _do_add(i: int) -> str:
            return store.add(
                _report(fingerprint=f"fp-shared-{i}", message=f"error {i}")
            )

        with ThreadPoolExecutor(max_workers=n) as pool:
            ids = list(pool.map(_do_add, range(n)))

        assert len(ids) == n
        assert len(set(ids)) == n  # every add() produced a distinct id
        assert len(store.list()) == n

    def test_concurrent_add_separate_instances_loses_no_rows(self, tmp_path):
        # Stronger proof of the hard constraint: each call uses its OWN
        # store instance (its own RLock), so nothing here is protected by
        # sharing one Python lock object -- only the SQL shape of add()
        # itself (a self-contained single-row INSERT that never reads the
        # whole table before writing) can prevent loss. A hypothetical
        # load()->append->save() reimplementation of add() would lose rows
        # under exactly this pattern even though each call is still
        # "atomic" from its own instance's point of view.
        db_path = tmp_path / "webui.db"
        # Pre-warm the schema once so concurrent instance construction below
        # only re-runs already-idempotent DDL, keeping the test focused on
        # add() itself rather than schema-creation contention.
        ErrorReportSqliteStore(WebUIDatabase(db_path))
        n = 20

        def _do_add(i: int) -> str:
            store = ErrorReportSqliteStore(WebUIDatabase(db_path))
            return store.add(
                _report(fingerprint=f"fp-sep-{i}", message=f"error {i}")
            )

        with ThreadPoolExecutor(max_workers=n) as pool:
            ids = list(pool.map(_do_add, range(n)))

        assert len(ids) == n
        assert len(set(ids)) == n

        reader = ErrorReportSqliteStore(WebUIDatabase(db_path))
        listed_ids = {r["id"] for r in reader.list()}
        assert listed_ids == set(ids)
        assert len(reader.list()) == n


# ── Lazy singleton (error_report_store) ─────────────────────────────────────

class TestLazySingleton:
    def test_resolves_and_persists_via_module_singleton(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store.error_reports import error_report_store
        error_report_store.reset()

        rid = error_report_store.add(_report(message="via singleton"))
        assert error_report_store.get(rid)["message"] == "via singleton"

    def test_singleton_path_is_webui_db_under_config_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        from webui_store.error_reports import error_report_store
        error_report_store.reset()

        assert error_report_store.path == tmp_path / "webui.db"
