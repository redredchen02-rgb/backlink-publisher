"""pipeline-orchestrator — orchestrate the full backlink publishing pipeline.

Replaces the ``run-full-pipeline.sh`` bash control flow with a structured
Python orchestrator. Each pipeline step is a subprocess call to the existing
CLI module, preserving the stdout=JSONL / stderr=diagnostics contract.

Usage::

    pipeline-orchestrator [-h] [--check] [--step STEPS] [--dry-run]

Modes:

- **default** (no flags) — run the full pipeline: equity-ledger → plan-gap →
  plan-backlinks → validate → publish.
- ``--check`` — evaluate whether a full pipeline run is due, based on gap
  density and time since last run. Exit 0 = skip, exit 0 with output "run" = go.
- ``--step equity-ledger,plan-gap`` — run only the named steps (comma-sep).

Environment variables (same as ``run-full-pipeline.sh``):

    BP_LANG, BP_DESIRED, BP_URL_MODE, BP_PUBLISH_MODE,
    BP_PLATFORM, BP_OPTIMIZE, BP_DRY_RUN, BP_MAX_ROWS

Plan 2026-06-10-002 U2.1 + U2.3.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, UTC
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Result of a single pipeline step."""

    name: str
    success: bool = False
    fatal: bool = False
    duration_s: float = 0.0
    exit_code: int = 0
    output: str = ""


@dataclass
class PipelineResult:
    """Aggregate result of a full pipeline run."""

    started_at: str
    completed_at: str = ""
    steps: list[StepResult] = field(default_factory=list)
    result: str = "unknown"  # success | partial | failed | skipped
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "message": self.message,
            "steps": [
                {
                    "name": s.name,
                    "success": s.success,
                    "fatal": s.fatal,
                    "duration_s": round(s.duration_s, 2),
                    "exit_code": s.exit_code,
                }
                for s in self.steps
            ],
        }


# ---------------------------------------------------------------------------
# Config (from env)
# ---------------------------------------------------------------------------

@dataclass
class PipelineConfig:
    """Configuration sourced from environment variables."""

    lang: str = "zh-CN"
    desired: int = 3
    url_mode: str = "A"
    publish_mode: str = "draft"
    platform: str = ""
    optimize: bool = True
    dry_run: bool = False
    max_rows: int = 1000

    @classmethod
    def from_env(cls) -> PipelineConfig:
        def _env(key: str, default: str) -> str:
            return os.environ.get(key, default)

        return cls(
            lang=_env("BP_LANG", "zh-CN"),
            desired=int(_env("BP_DESIRED", "3")),
            url_mode=_env("BP_URL_MODE", "A"),
            publish_mode=_env("BP_PUBLISH_MODE", "draft"),
            platform=_env("BP_PLATFORM", ""),
            optimize=_env("BP_OPTIMIZE", "1") == "1",
            dry_run=_env("BP_DRY_RUN", "0") == "1",
            max_rows=int(_env("BP_MAX_ROWS", "1000")),
        )


# ---------------------------------------------------------------------------
# Step runners
# ---------------------------------------------------------------------------

REPO_DIR = Path(__file__).resolve().parents[4]
VENV_PYTHON = REPO_DIR / ".venv" / "bin" / "python"


def _python_base() -> list[str]:
    """Return the Python executable list for subprocess calls."""
    if VENV_PYTHON.exists():
        return [str(VENV_PYTHON), "-m"]
    return [sys.executable, "-m"]


def _run_step(cmd: list[str], step_name: str) -> StepResult:
    """Execute a single pipeline step as a subprocess."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2h per step
        )
        duration = time.time() - start
        ok = result.returncode == 0
        return StepResult(
            name=step_name,
            success=ok,
            fatal=ok if step_name == "publish-backlinks" else (not ok),
            duration_s=duration,
            exit_code=result.returncode,
            output=result.stdout,
        )
    except subprocess.TimeoutExpired:
        return StepResult(
            name=step_name,
            success=False,
            fatal=True,
            duration_s=time.time() - start,
            exit_code=-1,
        )
    except FileNotFoundError:
        return StepResult(
            name=step_name,
            success=False,
            fatal=True,
            duration_s=time.time() - start,
            exit_code=-2,
        )


def _run_pipe_step(
    cmd: list[str], input_data: str | None, step_name: str
) -> tuple[StepResult, str]:
    """Execute a step with optional stdin pipe, returning (result, stdout)."""
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=7200,
        )
        duration = time.time() - start
        ok = result.returncode == 0
        return (
            StepResult(
                name=step_name,
                success=ok,
                fatal=not ok,
                duration_s=duration,
                exit_code=result.returncode,
            ),
            result.stdout,
        )
    except subprocess.TimeoutExpired:
        return (
            StepResult(
                name=step_name,
                success=False,
                fatal=True,
                duration_s=time.time() - start,
                exit_code=-1,
            ),
            "",
        )
    except FileNotFoundError:
        return (
            StepResult(
                name=step_name,
                success=False,
                fatal=True,
                duration_s=time.time() - start,
                exit_code=-2,
            ),
            "",
        )


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

STEPS_GAP = [
    "equity-ledger",
    "plan-gap",
    "plan-backlinks",
    "validate-backlinks",
    "publish-backlinks",
]

STEPS_ALL = [
    "equity-ledger",
    "plan-gap",
    "plan-backlinks",
    "validate-backlinks",
    "publish-backlinks",
    "recheck-backlinks",
    "optimize-weights",
]


def run_pipeline(
    config: PipelineConfig,
    step_names: list[str] | None = None,
) -> PipelineResult:
    """Execute the pipeline for the given steps (or full gap pipeline by default).

    Each step passes its stdout as stdin to the next step (UNIX pipe model).
    """
    if step_names is None:
        step_names = STEPS_GAP

    python = _python_base()
    result = PipelineResult(
        started_at=datetime.now(UTC).isoformat(),
    )

    prev_stdout: str | None = None

    for name in step_names:
        if name == "equity-ledger":
            cmd = [*python, "backlink_publisher.cli.equity_ledger"]
            sr, prev_stdout = _run_pipe_step(cmd, None, name)
        elif name == "plan-gap":
            if config.dry_run or not prev_stdout:
                sr = StepResult(name=name, success=True, fatal=False,
                                duration_s=0, exit_code=0)
            else:
                cmd = [
                    *python, "backlink_publisher.cli.plan_gap",
                    "--desired", str(config.desired),
                    "--language", config.lang,
                    "--url-mode", config.url_mode,
                    "--publish-mode", config.publish_mode,
                ]
                sr, prev_stdout = _run_pipe_step(cmd, prev_stdout, name)
                # No gaps → skip remaining steps
                if sr.success and not prev_stdout.strip():
                    result.steps.append(sr)
                    result.result = "skipped"
                    result.message = "No gaps to fill — all targets satisfied."
                    result.completed_at = datetime.now(UTC).isoformat()
                    return result
        elif name == "plan-backlinks":
            cmd = [
                *python, "backlink_publisher.cli.plan_backlinks",
                "--input", "/dev/stdin",
                "--language", config.lang,
            ]
            sr, prev_stdout = _run_pipe_step(cmd, prev_stdout, name)
        elif name == "validate-backlinks":
            cmd = [
                *python, "backlink_publisher.cli.validate_backlinks",
                "--input", "/dev/stdin",
                "--max-rows", str(config.max_rows),
            ]
            sr, prev_stdout = _run_pipe_step(cmd, prev_stdout, name)
        elif name == "publish-backlinks":
            if config.dry_run:
                sr = StepResult(name=name, success=True, fatal=False,
                                duration_s=0, exit_code=0)
            else:
                cmd = [
                    *python, "backlink_publisher.cli.publish_backlinks",
                    "--mode", config.publish_mode,
                    "--max-rows", str(config.max_rows),
                ]
                if config.platform:
                    cmd.extend(["--platform", config.platform])
                if config.optimize:
                    cmd.append("--optimize")
                sr, _ = _run_pipe_step(cmd, prev_stdout, name)
        elif name == "recheck-backlinks":
            cmd = [*python, "backlink_publisher.cli.recheck_backlinks", "--probe"]
            sr, _ = _run_pipe_step(cmd, None, name)
        elif name == "optimize-weights":
            cmd = [
                *python, "backlink_publisher.cli.weights", "optimize",
            ]
            sr, _ = _run_pipe_step(cmd, None, name)
        else:
            sr = StepResult(
                name=name, success=False, fatal=True,
                exit_code=-3, duration_s=0,
            )

        result.steps.append(sr)

        # Fatal error → stop pipeline
        if not sr.success and sr.fatal:
            result.result = "failed"
            result.message = f"Pipeline stopped at '{name}' (exit {sr.exit_code})"
            result.completed_at = datetime.now(UTC).isoformat()
            return result

    # Determine overall result
    successes = sum(1 for s in result.steps if s.success)
    if successes == len(result.steps):
        result.result = "success"
        result.message = "All steps completed successfully."
    elif successes > 0:
        result.result = "partial"
        result.message = f"{successes}/{len(result.steps)} steps succeeded."
    else:
        result.result = "failed"
        result.message = "All steps failed."

    result.completed_at = datetime.now(UTC).isoformat()
    return result


# ---------------------------------------------------------------------------
# Dynamic scheduling (U2.3)
# ---------------------------------------------------------------------------

SCHEDULER_STATE_DIR = REPO_DIR / "logs"
SCHEDULER_STATE_FILE = SCHEDULER_STATE_DIR / ".scheduler-state.json"


def _count_gaps(config: PipelineConfig) -> int:
    """Run equity-ledger + plan-gap in dry mode and count gap seeds.

    Returns 0 if no gaps, the number of gap seeds otherwise.
    """
    python = _python_base()

    # Step 1: equity-ledger
    ledger_result = _run_step(
        [*python, "backlink_publisher.cli.equity_ledger"],
        "equity-ledger",
    )
    if not ledger_result.success or not ledger_result.output:
        return 0

    ledger_out = ledger_result.output

    # Step 2: plan-gap to see how many gaps
    gap_cmd = [
        *python, "backlink_publisher.cli.plan_gap",
        "--desired", str(config.desired),
        "--language", config.lang,
        "--url-mode", config.url_mode,
        "--publish-mode", config.publish_mode,
    ]
    try:
        result = subprocess.run(
            gap_cmd,
            input=ledger_out,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    if result.returncode != 0:
        return 0

    gap_lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
    return len(gap_lines)


def _read_scheduler_state() -> dict[str, Any]:
    """Read the scheduler state JSON file."""
    if not SCHEDULER_STATE_FILE.exists():
        return {}
    try:
        return dict(json.loads(SCHEDULER_STATE_FILE.read_text()))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_scheduler_state(state: dict[str, Any]) -> None:
    """Write the scheduler state JSON file atomically."""
    SCHEDULER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SCHEDULER_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(SCHEDULER_STATE_FILE)


def should_run_now(config: PipelineConfig) -> tuple[bool, str]:
    """Decide whether the pipeline should run now based on gap density.

    Returns (should_run: bool, reason: str).

    Strategy:
        gap_count >= 5 and last_run >= 4h ago  → run
        gap_count >= 2 and last_run >= 8h ago  → run
        gap_count >= 1 and last_run >= 24h ago → run (daily minimum)
        otherwise → skip
    """
    gap_count = _count_gaps(config)
    state = _read_scheduler_state()
    now = time.time()
    last_run_ts = state.get("last_run_ts", 0)
    hours_since = (now - last_run_ts) / 3600 if last_run_ts else 999

    if gap_count == 0:
        return (False, f"no gaps (last run {hours_since:.1f}h ago)")

    # Dynamic thresholds
    if gap_count >= 5 and hours_since >= 4:
        return (True, f"{gap_count} gaps, {hours_since:.1f}h since last run")
    if gap_count >= 2 and hours_since >= 8:
        return (True, f"{gap_count} gaps, {hours_since:.1f}h since last run")
    if gap_count >= 1 and hours_since >= 24:
        return (True, f"{gap_count} gaps, {hours_since:.1f}h since last run (daily minimum)")

    next_at = max(4, 8, 24) if gap_count >= 5 else max(8, 24) if gap_count >= 2 else 24
    next_run = next_at - hours_since
    next_run_str = f"{next_run:.1f}h" if next_run > 0 else "soon"
    return (False, f"{gap_count} gaps, next run ~{next_run_str}")


def record_run() -> None:
    """Record that a pipeline run just completed."""
    state = _read_scheduler_state()
    state["last_run_ts"] = time.time()
    state["last_run_at"] = datetime.now(UTC).isoformat()
    _write_scheduler_state(state)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline-orchestrator",
        description="Orchestrate the full backlink publishing pipeline.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Should-run check only; exit 0='skip', stdout 'run'='go'.",
    )
    parser.add_argument(
        "--step",
        default=None,
        metavar="STEPS",
        help="Comma-separated step names to run (default: full gap pipeline).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview pipeline steps without side effects.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = PipelineConfig.from_env()
    if args.dry_run:
        config.dry_run = True

    # --check mode: evaluate whether we should run
    if args.check:
        should, reason = should_run_now(config)
        if should:
            print(reason)
            sys.exit(0)
        else:
            print(reason)
            sys.exit(0)

    # Determine steps
    step_names: list[str] | None = None
    if args.step:
        step_names = [s.strip() for s in args.step.split(",") if s.strip()]

    # Run the pipeline
    result = run_pipeline(config, step_names=step_names)

    # Record successful run for scheduler
    if result.result in ("success", "partial"):
        record_run()

    # Emit result as JSONL on stdout
    print(json.dumps(result.to_dict()))

    # Exit code: 0 = success/skipped, 1 = failure
    if result.result == "failed":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
