"""Tests for the generic os.environ leak guard (Plan 2026-07-07-003 Unit 6).

Context: docs/solutions/test-failures/del-os-environ-poisons-session-scoped-
config-dir-fixture-2026-05-27.md (and its two siblings in the same
directory) all trace back to one root-cause CLASS: a test mutates
``os.environ`` directly and never restores it, silently poisoning whichever
LATER test in the same session happens to depend on that variable -- and the
failure only reproduces under full-suite ordering, never when the polluted
test is run alone. ``tests/conftest.py`` now has an autouse
``_env_isolation_guard`` fixture (plus its pure comparison helper,
``_env_isolation_offenders``) that generalizes this protection to all of
``os.environ`` instead of the two specific keys the earlier incident hit.

Characterization-first note (per the plan's Execution note): before this
fixture existed, none of the existing autouse fixtures in tests/conftest.py
detected a bare ``del os.environ[...]`` leak at its source -- the only
existing state-restoring nets (``_isolate_user_dirs``,
``_reassert_config_isolation``, ``_restore_global_state_net``) either
restore a fixed, hand-named set of keys or only reset config-dir resolution;
none of them fail the *offending* test by name for an arbitrary leaked key.
This file's ``test_bare_del_is_detected_and_would_have_been_silent_before``
models exactly that gap and proves the new helper closes it.

Why this file calls ``_env_isolation_offenders`` directly instead of doing a
real nested pytest run: ``pytester``/``testdir`` ships with pytest core but
is not enabled in this project -- it requires ``pytest_plugins =
["pytester"]`` in the rootdir conftest, which is not set here (confirmed:
``pytest --fixtures`` does not list a ``pytester`` fixture unless pytest is
invoked with ``-p pytester`` on the command line). A real nested run would
also be the only way to prove the *autouse fixture itself* (not just its
comparison helper) fails the right test with the right message -- but since
that fixture applies to every test in this suite, deliberately triggering it
live inside a test function here would make that test permanently fail in a
green suite. So: the pure comparison logic is exercised directly and
exhaustively (this is where nearly all of the guard's decision-making
lives), and the ordering assumption the fixture depends on (monkeypatch
tears down before the guard's post-check runs) is instead verified
functionally via ``test_monkeypatch_setenv_does_not_false_positive`` below --
if that assumption were wrong, THIS suite's own guard would fail that test.
"""
from __future__ import annotations

__tier__ = "unit"

import os

from conftest import _ENV_GUARD_ALLOWLIST, _env_isolation_offenders


# ── Core helper behavior ─────────────────────────────────────────────────────


def test_bare_del_is_detected_and_would_have_been_silent_before() -> None:
    """Models exactly what `del os.environ["KEY"]` produces: present before,
    absent after. This is the precise shape from the 2026-05-27 incident doc
    (BACKLINK_PUBLISHER_CONFIG_DIR deleted, not restored) -- generalized here
    to an arbitrary key rather than that one specific name, since the guard
    is meant to catch ANY such leak, not just the historical one.
    """
    before = {"SOME_CONFIG_DIR": "/tmp/sandbox-abc", "UNRELATED": "1"}
    after = {"UNRELATED": "1"}
    assert _env_isolation_offenders(before, after) == ["SOME_CONFIG_DIR"]


def test_leaked_new_key_is_detected() -> None:
    """A test that sets a new env var directly (no monkeypatch, no cleanup)
    and never unsets it -- the mirror image of the bare-del case.
    """
    before = {"EXISTING": "1"}
    after = {"EXISTING": "1", "NEWLY_LEAKED": "oops"}
    assert _env_isolation_offenders(before, after) == ["NEWLY_LEAKED"]


def test_changed_value_without_del_is_detected() -> None:
    """Direct reassignment of an existing key (no delete involved at all)."""
    before = {"MODE": "isolated"}
    after = {"MODE": "real"}
    assert _env_isolation_offenders(before, after) == ["MODE"]


def test_multiple_offenders_are_all_named() -> None:
    before = {"A": "1", "B": "2", "C": "3"}
    after = {"A": "1", "B": "changed", "D": "new"}
    assert _env_isolation_offenders(before, after) == ["B", "C", "D"]


def test_no_diff_reports_no_offenders() -> None:
    snapshot = {"X": "1", "Y": "2"}
    assert _env_isolation_offenders(dict(snapshot), dict(snapshot)) == []


# ── Allowlist (Edge case: globally-pinned vars must not false-positive) ─────


def test_pythonhashseed_is_allowlisted() -> None:
    # Pinned via pyproject.toml [tool.pytest.ini_options] env = [...].
    assert "PYTHONHASHSEED" in _ENV_GUARD_ALLOWLIST


def test_allowlisted_key_change_does_not_false_positive() -> None:
    before = {"PYTHONHASHSEED": "0"}
    after = {"PYTHONHASHSEED": "1"}
    assert _env_isolation_offenders(before, after) == []


def test_allowlisted_key_deletion_does_not_false_positive() -> None:
    before = {"PYTHONHASHSEED": "0"}
    after: dict[str, str] = {}
    assert _env_isolation_offenders(before, after) == []


def test_allowlist_does_not_mask_other_keys_in_same_diff() -> None:
    """An allowlisted key changing alongside a real leak must still surface
    the real leak -- the allowlist exempts specific keys, not "any diff that
    happens to include one."
    """
    before = {"PYTHONHASHSEED": "0", "REAL_LEAK": "before"}
    after = {"PYTHONHASHSEED": "1", "REAL_LEAK": "after"}
    assert _env_isolation_offenders(before, after) == ["REAL_LEAK"]


# ── Happy path (Requirement: monkeypatch usage never false-positives) ──────


def test_monkeypatch_setenv_does_not_false_positive(monkeypatch) -> None:
    """Functional, not simulated: this genuinely runs under the real autouse
    ``_env_isolation_guard`` fixture from tests/conftest.py. monkeypatch is a
    plain (non-autouse) fixture requested by this test, so per pytest's
    ordering rules it is instantiated AFTER the autouse guard's setup and
    torn down BEFORE the guard's post-test check runs -- restoring
    BP_ENV_GUARD_TEST_KEY to its prior (absent) state first. If that
    ordering assumption were false, this test itself would fail under the
    guard rather than merely asserting something incorrect -- the strongest
    verification available without a nested pytest run.
    """
    assert "BP_ENV_GUARD_TEST_KEY" not in os.environ
    monkeypatch.setenv("BP_ENV_GUARD_TEST_KEY", "value")
    assert os.environ["BP_ENV_GUARD_TEST_KEY"] == "value"
    # No manual cleanup on purpose -- monkeypatch owns teardown.


def test_monkeypatch_delenv_does_not_false_positive(monkeypatch) -> None:
    """Same ordering guarantee, exercised via delenv on a key this test adds
    itself first (so we don't depend on any particular env var existing).
    """
    monkeypatch.setenv("BP_ENV_GUARD_DELENV_KEY", "temp")
    monkeypatch.delenv("BP_ENV_GUARD_DELENV_KEY")
    assert "BP_ENV_GUARD_DELENV_KEY" not in os.environ


def test_prior_test_env_var_did_not_leak_forward() -> None:
    """Confirms, at the top of a fresh test, that neither of the two
    monkeypatch tests above left their keys behind -- an end-to-end sanity
    check that the guard/monkeypatch combination actually protects
    downstream tests (collection order in this file is top-to-bottom, no
    pytest-randomly configured for this suite).
    """
    assert "BP_ENV_GUARD_TEST_KEY" not in os.environ
    assert "BP_ENV_GUARD_DELENV_KEY" not in os.environ
