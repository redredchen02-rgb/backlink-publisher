"""CLI-wiring tests for ``backlink_publisher.cli.plan_check`` (Unit 3).

D1 split (2026-07-02): extracted from ``test_cli_plan_check.py``. Covers
argparse dispatch, exit codes, ``--json`` output, and drift/fetch-outcome
surfacing. Uses the shared ``repo_with_origin`` fixture and ``_head_sha``
helper from ``tests/conftest.py`` (also consumed by
``test_cli_plan_check_git.py``).

Pattern (cf. tests/test_cli_footprint.py): import ``main`` directly, call in
process with ``capsys`` capturing stdout/stderr, assert exit code via
``pytest.raises(SystemExit)``. No subprocess for unit tests — only the
console-script smoke test goes via subprocess.
"""
from __future__ import annotations

__tier__ = "unit"
import json
from pathlib import Path

import pytest

from backlink_publisher.cli import plan_check as pc
from conftest import _head_sha  # type: ignore[import]


def _write_plan_doc(
    parent: Path,
    *,
    name: str,
    frontmatter: str,
    body: str = "\n# Plan\nbody\n",
) -> Path:
    """Drop a plan-doc at *parent / name* with the given frontmatter block."""
    p = parent / name
    p.write_text(f"---\n{frontmatter}\n---\n{body}")
    return p


class TestCliHappyPaths:
    def test_grandfathered_plan_silent_exit_0(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        # Pre-cutoff date → silent exit 0; no stdout, no stderr, no JSON.
        # Success is a clean ``return`` from ``main`` (no SystemExit).
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-19-001-old-plan.md",
            frontmatter="date: 2026-05-19",
        )
        result = pc.main([str(plan)])
        assert result is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_empty_claims_block_silent_exit_0(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        # Post-cutoff plan-doc with `claims: {}` — explicit opt-out; silent.
        monkeypatch.chdir(repo_with_origin)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-empty-plan.md",
            frontmatter="date: 2026-05-21\nclaims: {}",
        )
        result = pc.main([str(plan)])
        assert result is None
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_all_claims_resolve_pass_summary(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        main_sha = _head_sha(repo_with_origin, "origin/main")
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-pass-plan.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/foo.py\n"
                "  shas:\n"
                # YAML-quote the SHA: an all-digit 7-char short hash (~5% of
                # random SHAs) parses as int otherwise. Schema correctly
                # rejects ints; the fixture must declare strings.
                f"    - '{main_sha[:7]}'\n"
            ),
        )
        result = pc.main([str(plan)])
        assert result is None
        captured = capsys.readouterr()
        assert "plan-check: pass" in captured.out
        assert "1 paths" in captured.out
        assert "1 shas" in captured.out
        # RECON line on stderr (info — fetch was fresh after fixture's fetch)
        assert "RECON" in captured.err

    def test_json_flag_pass_payload(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-json-pass.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/foo.py\n"
                "  shas: []\n"
            ),
        )
        result = pc.main([str(plan), "--json"])
        assert result is None
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["schema_version"] == 1
        assert payload["status"] == "pass"
        assert payload["exit_code"] == 0
        # fetch_head_age_seconds is int (we ran fetch in fixture)
        assert isinstance(payload["fetch_head_age_seconds"], int)
        assert payload["fetch_skip_reason"] is None
        assert payload["drift"] == {"paths_missing": [], "shas_unreachable": []}
        assert payload["date"] == "2026-05-21"
        # fetched_at is ISO-8601 UTC ending with Z
        assert payload["fetched_at"].endswith("Z")


class TestCliUsageErrors:
    def test_positional_is_directory_exits_1(
        self, tmp_path: Path, capsys
    ) -> None:
        d = tmp_path / "not-a-file"
        d.mkdir()
        with pytest.raises(SystemExit) as exc:
            pc.main([str(d)])
        assert exc.value.code == 1

    def test_positional_nonexistent_file_exits_1(
        self, tmp_path: Path, capsys
    ) -> None:
        missing = tmp_path / "ghost.md"
        with pytest.raises(SystemExit) as exc:
            pc.main([str(missing)])
        assert exc.value.code == 1

    def test_no_arg_exits_via_argparse(self, capsys) -> None:
        with pytest.raises(SystemExit) as exc:
            pc.main([])
        # argparse itself exits 2 on missing positional — we accept the overlap
        # with schema-violation 2 because argparse only fires on usage issues.
        assert exc.value.code == 2


class TestCliSchemaViolations:
    def test_malformed_yaml_exits_2(
        self, tmp_path: Path, capsys
    ) -> None:
        # Build a plan-doc with bogus YAML (unbalanced bracket).
        p = tmp_path / "2026-05-21-001-bad-yaml.md"
        p.write_text("---\ndate: 2026-05-21\nclaims: {paths: [\n---\nbody\n")
        with pytest.raises(SystemExit) as exc:
            pc.main([str(p)])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "schema violation" in captured.err

    def test_unknown_claims_key_exits_2_message_names_key(
        self, tmp_path: Path, capsys
    ) -> None:
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-unknown-key.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths: []\n"
                "  symbols:\n"
                "    - foo\n"
            ),
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan)])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "symbols" in captured.err

    def test_glob_in_paths_exits_2(self, tmp_path: Path, capsys) -> None:
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-glob.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/*.py\n"
            ),
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan)])
        assert exc.value.code == 2

    def test_filename_date_mismatch_exits_2(
        self, tmp_path: Path, capsys
    ) -> None:
        # Filename says 2026-05-21 but frontmatter says 2026-05-19 (backdate)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-backdate.md",
            frontmatter="date: 2026-05-19\nclaims: {}",
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan)])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        # Both dates surfaced in the message
        assert "2026-05-21" in captured.err
        assert "2026-05-19" in captured.err


class TestCliMissingClaims:
    def test_post_cutoff_missing_claims_exits_8(
        self, tmp_path: Path, capsys
    ) -> None:
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-no-claims.md",
            frontmatter="date: 2026-05-21",
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan)])
        assert exc.value.code == 8
        captured = capsys.readouterr()
        assert "claims" in captured.err.lower()

    def test_post_cutoff_missing_claims_json_payload(
        self, tmp_path: Path, capsys
    ) -> None:
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-no-claims-json.md",
            frontmatter="date: 2026-05-21",
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan), "--json"])
        assert exc.value.code == 8
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["status"] == "missing_claims"
        assert payload["exit_code"] == 8


class TestCliDrift:
    def test_paths_drift_exits_7_with_table(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-path-drift.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/foo.py\n"           # exists on main
                "    - never/touched.py\n"      # never existed → drift
            ),
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan)])
        assert exc.value.code == 7
        captured = capsys.readouterr()
        # stderr: drift table mentioning the missing path
        assert "Drift detected" in captured.err
        assert "never/touched.py" in captured.err
        assert "paths_missing" in captured.err
        # stdout: summary one-liner
        assert "1 paths missing" in captured.out

    def test_shas_drift_exits_7_with_table(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        feat_sha = _head_sha(repo_with_origin, "feat/x")
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-sha-drift.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths: []\n"
                "  shas:\n"
                f"    - '{feat_sha}'\n"  # exists in DB but not on main; quoted to keep PyYAML from int-coercing an all-digit hash
            ),
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan)])
        assert exc.value.code == 7
        captured = capsys.readouterr()
        assert "shas_unreachable" in captured.err
        assert feat_sha in captured.err

    def test_drift_json_payload_matches_human(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        # Same drift state surfaced via --json — paths_missing must match the
        # human table set exactly (integration scenario in plan §Unit 3).
        monkeypatch.chdir(repo_with_origin)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-drift-json.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - never/one.py\n"
                "    - never/two.py\n"
            ),
        )
        with pytest.raises(SystemExit) as exc:
            pc.main([str(plan), "--json"])
        assert exc.value.code == 7
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["status"] == "drift"
        assert payload["exit_code"] == 7
        assert set(payload["drift"]["paths_missing"]) == {
            "never/one.py",
            "never/two.py",
        }
        assert payload["drift"]["shas_unreachable"] == []


class TestCliFetchOutcomeSurface:
    def test_recon_warn_emitted_when_fetch_skipped(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        # Inject a synthetic FetchOutcome with skip_reason="network" via
        # monkeypatch, then assert the CLI still runs drift detection AND
        # emits the structured `RECON warn fetch_skipped` line per D16.
        monkeypatch.chdir(repo_with_origin)
        fake_outcome = pc.FetchOutcome(
            fetched=False,
            fetch_head_age_seconds=8 * 3600,  # 8h stale
            skip_reason="network",
        )
        monkeypatch.setattr(pc, "_maybe_fetch_origin_main", lambda: fake_outcome)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-stale-pass.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/foo.py\n"
            ),
        )
        # Drift resolution still ran (src/foo.py is on main) → clean return.
        result = pc.main([str(plan)])
        assert result is None
        captured = capsys.readouterr()
        assert "RECON warn fetch_skipped" in captured.err
        assert "reason=network" in captured.err
        assert "fetch_head_age_seconds=28800" in captured.err

    def test_recon_info_on_happy_fetch(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(repo_with_origin)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-info-recon.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/foo.py\n"
            ),
        )
        result = pc.main([str(plan)])
        assert result is None
        captured = capsys.readouterr()
        assert "RECON info fetch_head_age_seconds=" in captured.err

    def test_json_payload_carries_skip_reason_and_age(
        self, repo_with_origin: Path, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        # Locks the JSON contract for downstream tooling: when fetch was
        # skipped, both `fetch_skip_reason` and `fetch_head_age_seconds`
        # are present with the correct values.
        monkeypatch.chdir(repo_with_origin)
        fake_outcome = pc.FetchOutcome(
            fetched=False,
            fetch_head_age_seconds=42,
            skip_reason="network",
        )
        monkeypatch.setattr(pc, "_maybe_fetch_origin_main", lambda: fake_outcome)
        plan = _write_plan_doc(
            tmp_path,
            name="2026-05-21-001-json-stale.md",
            frontmatter=(
                "date: 2026-05-21\n"
                "claims:\n"
                "  paths:\n"
                "    - src/foo.py\n"
            ),
        )
        # All claims resolved against (possibly stale) origin/main → pass.
        result = pc.main([str(plan), "--json"])
        assert result is None
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["fetch_skip_reason"] == "network"
        assert payload["fetch_head_age_seconds"] == 42
