""":mod:`bp-report-bug` CLI entrypoint.

Captures an error into a self-contained, secret-redacted bug report the operator
can hand to a coding agent. Three capture paths:

  - ``--wrap "CMD"``   run any existing command as a subprocess; on non-zero exit
                       capture its stderr automatically (zero edits to other
                       entrypoints, stdout passes through untouched). Add
                       ``--shell`` to run via the system shell (pipes, ``&&``).
  - ``--stderr-file F`` read a saved error log file.
  - ``-`` / ``--paste`` read the error text from stdin.

Regardless of capture path, the report always enriches the error with an
environment snapshot, a sanitized config snapshot, storage health, recent runs,
and class-specific remediation hints.

Management sub-actions (no capture needed): ``--list`` (enumerate saved
reports), ``--prune-days N`` (delete reports older than N days), ``--open``
(reveal the most recent report with the OS handler).

Output contract: the report is written to disk (0600); stdout emits one JSONL
line with the report paths; human-facing summary goes to stderr. ``--json``
adds the full report object to that stdout line.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from backlink_publisher._util.error_envelope import parse as parse_envelope
from backlink_publisher._util.paths import _cache_dir
from backlink_publisher.cli.report_bug._build import (
    build_report,
    ReportInput,
    save_report,
)

_RUN_ID_RE = __import__("re").compile(r"\brun_id=(\S+)")


def _extract_run_id(text: str) -> str | None:
    m = _RUN_ID_RE.search(text)
    return m.group(1) if m else None


def _default_output_dir() -> str:
    return str(_cache_dir() / "bug-reports")


def _iter_report_pairs(output_dir: str) -> list[tuple[Path, Path]]:
    """Return (markdown, json) pairs in ``output_dir``, newest-first."""
    base = Path(output_dir)
    if not base.is_dir():
        return []
    pairs: list[tuple[Path, Path]] = []
    for md in base.glob("*.md"):
        json_path = md.with_suffix(".json")
        pairs.append((md, json_path))
    pairs.sort(key=lambda p: p[0].stat().st_mtime, reverse=True)
    return pairs


def _list_reports(output_dir: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for md, jp in _iter_report_pairs(output_dir):
        st = md.stat()
        out.append(
            {
                "name": md.name,
                "markdown": str(md),
                "json": str(jp) if jp.exists() else None,
                "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                "size_bytes": st.st_size,
            }
        )
    return out


def _prune_reports(output_dir: str, days: int) -> int:
    """Delete report pairs older than ``days`` days. Returns count removed."""
    if days <= 0:
        return 0
    cutoff = datetime.now().timestamp() - (days * 86400)
    removed = 0
    for md, jp in _iter_report_pairs(output_dir):
        try:
            if md.stat().st_mtime < cutoff:
                md.unlink(missing_ok=True)
                jp.unlink(missing_ok=True)
                removed += 1
        except OSError:
            pass
    return removed


def _open_report(output_dir: str) -> str | None:
    """Open the most recent report with the OS handler. Returns its path or None."""
    pairs = _iter_report_pairs(output_dir)
    if not pairs:
        return None
    target = pairs[0][0]
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
    except Exception as exc:  # noqa: BLE001 — best-effort open
        print(f"bp-report-bug: could not open report: {exc}", file=sys.stderr)
        return None
    return str(target)


def _run_wrapped(cmd: str, shell: bool = False) -> tuple[int, str]:
    """Run ``cmd`` via subprocess; pass stdout through, buffer+echo stderr.

    Returns (returncode, captured_stderr). stdout is inherited so the user sees
    the wrapped command's real output; only stderr is captured for the report.
    With ``shell=True`` the command string is passed to the system shell (so
    pipes / ``&&`` work), at the cost of shell-interpretation of the string.
    """
    if shell:
        argv: list[str] | str = cmd
    else:
        try:
            # `posix=False` on Windows so backslash-rich paths (e.g. the venv
            # python executable) are not mangled as POSIX escape sequences.
            argv = shlex.split(cmd, posix=os.name == "posix")
        except ValueError as exc:
            print(f"bp-report-bug: could not parse --wrap command: {exc}", file=sys.stderr)
            raise SystemExit(2)

    proc = subprocess.Popen(
        argv,
        stdout=None,  # inherit — never mask the wrapped command's output
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        shell=shell,
    )
    captured: list[str] = []
    assert proc.stderr is not None
    for line in proc.stderr:
        sys.stderr.write(line)
        sys.stderr.flush()
        captured.append(line)
    proc.wait()
    return proc.returncode, "".join(captured)


def _read_stdin() -> str:
    return sys.stdin.read()


def _maybe_prompt_describe(args: argparse.Namespace) -> str | None:
    if args.describe is not None:
        return str(args.describe)
    if sys.stdin.isatty():
        try:
            return input("請簡述你遇到的問題 (可留空): ").strip() or None
        except (EOFError, KeyboardInterrupt):
            return None
    return None


def _emit(record: dict) -> None:
    print(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> NoReturn:
    parser = argparse.ArgumentParser(
        prog="bp-report-bug",
        description="Capture an error into a redacted, coding-agent-ready bug report.",
    )
    parser.add_argument("--wrap", metavar="CMD", help="Wrap and run this command; capture its stderr on failure.")
    parser.add_argument("--shell", action="store_true", help="Run --wrap via the system shell (allows pipes, &&).")
    parser.add_argument("--stderr-file", metavar="PATH", help="Read a saved error log file.")
    parser.add_argument("-", "--paste", action="store_true", help="Read the error text from stdin.")
    parser.add_argument("--describe", help="Free-form description of the problem.")
    parser.add_argument("--run-id", help="Associated run_id (for repro hint).")
    parser.add_argument("--output", metavar="DIR", help="Report output directory (default: <cache>/bug-reports).")
    parser.add_argument("--json", action="store_true", help="Include the full report object on stdout.")
    parser.add_argument("--no-redact", action="store_true", help="Disable redaction (NOT recommended — leaks secrets).")
    parser.add_argument("--list", action="store_true", help="List saved bug reports and exit (no capture).")
    parser.add_argument("--prune-days", type=int, default=None, metavar="N", help="Delete bug reports older than N days and exit.")
    parser.add_argument("--open", action="store_true", help="Open the most recent bug report with the OS handler and exit.")
    args = parser.parse_args(argv)

    output_dir = args.output or _default_output_dir()

    # ── Management sub-actions (no error capture needed) ─────────────────────
    if args.list:
        reports = _list_reports(output_dir)
        if args.json:
            _emit({"reports": reports})
        else:
            if not reports:
                print("No saved bug reports.", file=sys.stderr)
            for r in reports:
                print(f"{r['modified']}  {r['name']}  ({r['size_bytes']} bytes)", file=sys.stderr)
        raise SystemExit(0)

    if args.prune_days is not None:
        removed = _prune_reports(output_dir, args.prune_days)
        print(f"bp-report-bug: pruned {removed} report(s) older than {args.prune_days} days.", file=sys.stderr)
        _emit({"pruned": removed})
        raise SystemExit(0)

    if args.open:
        opened = _open_report(output_dir)
        if opened:
            print(f"bp-report-bug: opened {opened}", file=sys.stderr)
            _emit({"opened": opened})
        else:
            print("bp-report-bug: no saved report to open.", file=sys.stderr)
            _emit({"opened": None})
        raise SystemExit(0)

    # ── Capture + build ───────────────────────────────────────────────────────
    redact = not args.no_redact
    if not redact:
        print(
            "bp-report-bug: --no-redact set — secrets will NOT be masked. "
            "Do not share the resulting file publicly.",
            file=sys.stderr,
        )

    command: str | None = None
    stderr_text = ""
    run_id = args.run_id

    if args.wrap:
        command = args.wrap
        code, stderr_text = _run_wrapped(args.wrap, shell=args.shell)
        if run_id is None:
            run_id = _extract_run_id(stderr_text)
        if code == 0:
            print(
                "bp-report-bug: wrapped command exited 0 — no error captured, no report written.",
                file=sys.stderr,
            )
            raise SystemExit(0)
    elif args.stderr_file:
        path = Path(args.stderr_file)
        if not path.exists():
            print(f"bp-report-bug: stderr file not found: {path}", file=sys.stderr)
            raise SystemExit(2)
        stderr_text = path.read_text(encoding="utf-8", errors="replace")
    elif args.paste:
        stderr_text = _read_stdin()
    else:
        # No capture source: require at least a description, else insufficient input.
        describe = _maybe_prompt_describe(args)
        if not describe:
            print(
                "bp-report-bug: no error source (--wrap/--stderr-file/-) and no --describe given.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        args.describe = describe

    describe = _maybe_prompt_describe(args)
    envelope = parse_envelope(stderr_text) if stderr_text else None

    inp = ReportInput(
        envelope=envelope,
        stderr_text=stderr_text,
        command=command,
        run_id=run_id,
        describe=describe,
    )

    try:
        report = build_report(inp, redact=redact)
        md_path, json_path = save_report(report, output_dir, redact=redact)
    except Exception as exc:  # noqa: BLE001 — report build must never crash the session
        print(f"bp-report-bug: failed to build report: {exc}", file=sys.stderr)
        raise SystemExit(5)

    print("Bug report written:", file=sys.stderr)
    print(f"  markdown: {md_path}", file=sys.stderr)
    print(f"  json:     {json_path}", file=sys.stderr)
    if report.get("error", {}).get("error_class") not in (None, "unknown"):
        print(f"  error:    {report['error']['error_class']}", file=sys.stderr)

    record: dict[str, object] = {"report_path": str(md_path), "json_path": str(json_path)}
    if args.json:
        record["report"] = report
    _emit(record)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
