"""Git-tier tests for ``backlink_publisher.cli.plan_check`` (Unit 2).

D1 split (2026-07-02): extracted from ``test_cli_plan_check.py``, which
originally carried schema-tier (Unit 1), git-tier (Unit 2), and CLI-wiring
(Unit 3) tests in one file. The ``repo_with_origin`` / ``_origin_repo_template``
fixtures and the ``_git`` / ``_head_sha`` helpers moved to ``tests/conftest.py``
because both this file and ``test_cli_plan_check_cli.py`` need them.

We exercise real git via ``subprocess.run`` (through the shared ``_git``
helper) in tmp_path-isolated fixtures, never mocking ``subprocess`` itself —
the value of these tests is that the exit-code discrimination (0 / 1 / 128)
actually matches real git behaviour (per
``tests/scripts/test_prune_stale_worktrees.py`` pattern).

Tested surface:
- ``_fetch_head_age_seconds`` / ``_maybe_fetch_origin_main`` (D5/D16)
- ``_path_exists_on_main`` / ``_sha_reachable_from_main`` (R2/R3)
- ``FetchOutcome`` dataclass shape
"""
from __future__ import annotations

__tier__ = "unit"
import os
from pathlib import Path
import time

import pytest

from backlink_publisher.cli import _plan_check_git as pc_git
from backlink_publisher.cli import plan_check as pc
from conftest import _git, _head_sha  # type: ignore[import]


class TestPathExistsOnMain:
    def test_happy_path_root_file(self, repo_with_origin: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo_with_origin)
        assert pc._path_exists_on_main("src/foo.py") == (True, "exists")

    def test_happy_path_nested_directory(self, repo_with_origin: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo_with_origin)
        assert pc._path_exists_on_main("src/foo/bar.py") == (True, "exists")

    def test_missing_path_returns_missing(self, repo_with_origin: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo_with_origin)
        # The file lives only on feat/x, never on main
        assert pc._path_exists_on_main("extra.py") == (False, "missing")

    def test_truly_absent_path_returns_missing(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        # Never existed in any tree
        assert pc._path_exists_on_main("never/touched.py") == (False, "missing")

    def test_outside_git_repo_returns_git_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # cwd is a fresh tmp dir, not a git repo at all
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)
        ok, status = pc._path_exists_on_main("anything.py")
        assert ok is False
        assert status == "git_error"


class TestShaReachableFromMain:
    def test_happy_path_full_sha(self, repo_with_origin: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo_with_origin)
        full = _head_sha(repo_with_origin, "origin/main")
        assert pc._sha_reachable_from_main(full) == (True, "reachable")

    def test_short_sha_works_same_as_full(self, repo_with_origin: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo_with_origin)
        short = _head_sha(repo_with_origin, "origin/main")[:7]
        assert pc._sha_reachable_from_main(short) == (True, "reachable")

    def test_sha_only_on_feature_branch_is_unreachable(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        feat_sha = _head_sha(repo_with_origin, "feat/x")
        main_sha = _head_sha(repo_with_origin, "origin/main")
        assert feat_sha != main_sha
        # Object DB knows the sha (we just committed it), but it's NOT an
        # ancestor of origin/main — that's exit 1 → "unreachable".
        assert pc._sha_reachable_from_main(feat_sha) == (False, "unreachable")

    def test_unknown_object_returns_unknown_object(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        # 7 lowercase hex chars that very plausibly aren't in the object DB
        ok, status = pc._sha_reachable_from_main("dead1234beef5678cafe9012345678901234abcd")
        assert ok is False
        assert status == "unknown_object"


class TestFetchHeadAgeSeconds:
    def test_returns_inf_outside_git_repo(self, tmp_path: Path, monkeypatch) -> None:
        non_repo = tmp_path / "not-a-repo"
        non_repo.mkdir()
        monkeypatch.chdir(non_repo)
        assert pc._fetch_head_age_seconds() == float("inf")

    def test_returns_inf_when_fetch_head_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # A fresh repo with no remote / no fetch yet → no FETCH_HEAD file.
        repo = tmp_path / "fresh"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        monkeypatch.chdir(repo)
        # Sanity: FETCH_HEAD must not exist
        assert not (repo / ".git" / "FETCH_HEAD").exists()
        assert pc._fetch_head_age_seconds() == float("inf")

    def test_age_reflects_real_mtime(self, repo_with_origin: Path, monkeypatch) -> None:
        monkeypatch.chdir(repo_with_origin)
        # repo_with_origin fixture ran `git fetch -q origin` so FETCH_HEAD exists
        fh = repo_with_origin / ".git" / "FETCH_HEAD"
        assert fh.exists()
        # Backdate FETCH_HEAD to 1000s ago via os.utime
        now = time.time()
        os.utime(fh, (now - 1000, now - 1000))
        age = pc._fetch_head_age_seconds()
        assert 990 <= age <= 1100, f"age was {age!r}"


class TestMaybeFetchOriginMain:
    def test_under_threshold_skips_fetch(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        fh = repo_with_origin / ".git" / "FETCH_HEAD"
        now = time.time()
        # 299s ago — under default 300s threshold
        os.utime(fh, (now - 299, now - 299))
        outcome = pc._maybe_fetch_origin_main()
        assert isinstance(outcome, pc.FetchOutcome)
        assert outcome.fetched is False
        assert outcome.skip_reason is None
        # Age populated, finite, and roughly correct
        assert outcome.fetch_head_age_seconds is not None
        assert 290 <= outcome.fetch_head_age_seconds <= 310

    def test_over_threshold_triggers_fetch(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        fh = repo_with_origin / ".git" / "FETCH_HEAD"
        now = time.time()
        # 301s ago — above default 300s threshold → real `git fetch` runs.
        # Remote is a local bare clone created in the fixture, so this should
        # succeed end-to-end without network.
        os.utime(fh, (now - 301, now - 301))
        outcome = pc._maybe_fetch_origin_main()
        assert isinstance(outcome, pc.FetchOutcome)
        assert outcome.fetched is True
        assert outcome.skip_reason is None
        # After a real fetch, FETCH_HEAD mtime is roughly "now" → age small.
        assert outcome.fetch_head_age_seconds is not None
        assert outcome.fetch_head_age_seconds < 60

    def test_missing_fetch_head_triggers_fetch(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        fh = repo_with_origin / ".git" / "FETCH_HEAD"
        if fh.exists():
            fh.unlink()
        outcome = pc._maybe_fetch_origin_main()
        assert outcome.fetched is True
        assert outcome.skip_reason is None
        assert outcome.fetch_head_age_seconds is not None

    def test_network_failure_classified_no_raise(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Build a repo whose origin points at an unresolvable host. Real
        # `git fetch` will emit "Could not resolve host" under LC_ALL=C.
        repo = tmp_path / "net-broken"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "f").write_text("x")
        _git(repo, "add", "f")
        _git(repo, "commit", "-q", "-m", "init")
        _git(repo, "remote", "add", "origin", "https://does-not-resolve.invalid/x.git")
        monkeypatch.chdir(repo)
        # Force stale so the fetch path runs
        outcome = pc._maybe_fetch_origin_main(threshold_seconds=0)
        assert outcome.fetched is False
        assert outcome.skip_reason == "network"

    def test_no_remote_failure_classified(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Origin points at a nonexistent local directory → "does not appear
        # to be a git repository" stderr under LC_ALL=C.
        repo = tmp_path / "no-remote"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "f").write_text("x")
        _git(repo, "add", "f")
        _git(repo, "commit", "-q", "-m", "init")
        bogus = tmp_path / "definitely-not-a-repo"
        _git(repo, "remote", "add", "origin", str(bogus))
        monkeypatch.chdir(repo)
        outcome = pc._maybe_fetch_origin_main(threshold_seconds=0)
        assert outcome.fetched is False
        assert outcome.skip_reason == "no_remote"

    def test_auth_failure_classified(self, monkeypatch) -> None:
        # Construct a synthetic stderr through the classifier helper. We don't
        # try to trigger a real auth failure (would need a live private repo);
        # the regression value is locking the substring → reason mapping.
        assert pc._classify_fetch_stderr("fatal: Authentication failed for 'x'") == "auth"
        assert pc._classify_fetch_stderr("Permission denied (publickey).") == "auth"
        assert pc._classify_fetch_stderr("fatal: could not read Username for 'x': terminal prompts disabled") == "auth"

    def test_other_failure_classified(self) -> None:
        assert pc._classify_fetch_stderr("fatal: something weird happened") == "other"
        # Empty stderr also falls into "other"
        assert pc._classify_fetch_stderr("") == "other"

    def test_fetch_failure_age_field_well_typed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Plan §Unit 2 scenario 13: when fetch fails AND ``FETCH_HEAD`` does not
        # resolve, the outcome must carry ``fetch_head_age_seconds=None``.
        # In practice real git creates an empty FETCH_HEAD even on a failed
        # connect, so the empty-file path is what actually exercises the
        # contract: the field is ``int | None`` (never absent, never ``inf``).
        # We additionally simulate the truly-missing case by deleting
        # FETCH_HEAD before the function returns; that's tested by going
        # through the helper ``_fetch_head_age_seconds`` directly.
        repo = tmp_path / "broken-no-fh"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "f").write_text("x")
        _git(repo, "add", "f")
        _git(repo, "commit", "-q", "-m", "init")
        _git(repo, "remote", "add", "origin", "https://does-not-resolve.invalid/x.git")
        fh = repo / ".git" / "FETCH_HEAD"
        if fh.exists():
            fh.unlink()
        monkeypatch.chdir(repo)
        outcome = pc._maybe_fetch_origin_main(threshold_seconds=0)
        assert outcome.fetched is False
        assert outcome.skip_reason == "network"
        # ``age`` is either ``None`` (truly missing) or an ``int`` (git wrote an
        # empty FETCH_HEAD as a side-effect of the failed fetch). Never ``inf``,
        # never a ``float``, never absent.
        assert outcome.fetch_head_age_seconds is None or isinstance(
            outcome.fetch_head_age_seconds, int
        )

    def test_fetch_head_truly_missing_yields_none_via_helper(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Direct contract for the FETCH_HEAD-absent branch: if the file is
        # genuinely not on disk, ``_fetch_head_age_seconds`` returns ``inf``
        # and ``_maybe_fetch_origin_main`` converts that to ``None`` on the
        # failure path (D16). We simulate by monkeypatching the helper so the
        # post-fetch stat sees no file.
        repo = tmp_path / "broken-mp"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")
        (repo / "f").write_text("x")
        _git(repo, "add", "f")
        _git(repo, "commit", "-q", "-m", "init")
        _git(repo, "remote", "add", "origin", "https://does-not-resolve.invalid/x.git")
        monkeypatch.chdir(repo)
        monkeypatch.setattr(pc_git, "_fetch_head_age_seconds", lambda: float("inf"))
        outcome = pc._maybe_fetch_origin_main(threshold_seconds=0)
        assert outcome.fetched is False
        assert outcome.skip_reason == "network"
        assert outcome.fetch_head_age_seconds is None

    def test_age_always_populated_or_none_on_every_path(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        """D16 contract: ``fetch_head_age_seconds`` is always ``int`` or ``None``,
        never absent. We probe both the skip-branch and the fetch-success branch."""
        monkeypatch.chdir(repo_with_origin)
        fh = repo_with_origin / ".git" / "FETCH_HEAD"
        now = time.time()
        # Skip branch
        os.utime(fh, (now - 10, now - 10))
        out_skip = pc._maybe_fetch_origin_main()
        assert out_skip.fetch_head_age_seconds is not None
        assert isinstance(out_skip.fetch_head_age_seconds, int)
        # Fetch branch
        os.utime(fh, (now - 1000, now - 1000))
        out_fetch = pc._maybe_fetch_origin_main()
        assert out_fetch.fetch_head_age_seconds is None or isinstance(
            out_fetch.fetch_head_age_seconds, int
        )


class TestFetchOutcomeDataclass:
    def test_frozen(self) -> None:
        outcome = pc.FetchOutcome(
            fetched=True, fetch_head_age_seconds=5, skip_reason=None
        )
        with pytest.raises(Exception):
            # frozen dataclass must reject attribute assignment
            outcome.fetched = False  # type: ignore[misc]

    def test_fields_present(self) -> None:
        outcome = pc.FetchOutcome(
            fetched=False, fetch_head_age_seconds=None, skip_reason="network"
        )
        assert outcome.fetched is False
        assert outcome.fetch_head_age_seconds is None
        assert outcome.skip_reason == "network"


class TestGitResolutionIntegration:
    def test_full_path_and_sha_resolution_end_to_end(
        self, repo_with_origin: Path, monkeypatch
    ) -> None:
        """Integration: tmp repo with two commits — one on main, one on feature —
        exercises the full ``_path_exists_on_main`` + ``_sha_reachable_from_main``
        layer in one fixture (plan §Unit 2 test scenario 15)."""
        monkeypatch.chdir(repo_with_origin)
        # Path on main: exists
        assert pc._path_exists_on_main("src/foo.py") == (True, "exists")
        # Path on feature branch only: missing on main
        assert pc._path_exists_on_main("extra.py") == (False, "missing")
        # SHA on main: reachable
        main_sha = _head_sha(repo_with_origin, "origin/main")
        assert pc._sha_reachable_from_main(main_sha) == (True, "reachable")
        # SHA on feature branch only: unreachable
        feat_sha = _head_sha(repo_with_origin, "feat/x")
        assert pc._sha_reachable_from_main(feat_sha) == (False, "unreachable")
