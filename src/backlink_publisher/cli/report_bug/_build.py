"""Diagnostic-bundle assembly for ``bp-report-bug`` and the WebUI report route.

Builds a self-contained, secret-redacted report the operator can hand to a
coding agent. The report collects, in one place:

  - the typed error (parsed from the ``__BLP_ERR__`` envelope or supplied directly)
  - a sanitized environment snapshot (OS / Python / package version / paths /
    git / env-var *names* only)
  - a sanitized config snapshot (file *names* + credential permission audit)
  - storage health (reuses :mod:`backlink_publisher.cli.ops.health_check`)
  - recent checkpoint runs
  - a redacted tail of the captured stderr
  - suggested fixes keyed off the error class

Redaction is defense-in-depth: every structured section is walked by
``_util.logger._redact_in_place`` (sensitive-key scrubber), and free-text
(stderr tail, error message) is scrubbed by a targeted regex that masks
``token=...`` / ``Bearer ...`` / ``authorization: ...`` shapes. The report is
designed to be safe to paste into an external chat.

This module lives under ``cli`` (domain) so it may import ``health_check`` and
``checkpoint``; it imports from ``_util`` (allowed direction) but never the
reverse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import json
import math as _math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from backlink_publisher import checkpoint
from backlink_publisher._util.error_envelope import ErrorEnvelope
from backlink_publisher._util.error_envelope import parse as parse_envelope
from backlink_publisher._util.logger import _redact_in_place
from backlink_publisher._util.paths import _cache_dir, _config_dir
from backlink_publisher.cli.ops.health_check import _check_all

# Recent-run cap and stderr-tail cap.
_RECENT_RUNS_LIMIT = 10
_STDERR_TAIL_LINES = 120

# Targeted free-text scrubber. Three layers (mirrors the WebUI
# ``error_report_sanitizer`` composition, but self-contained in core so the
# CLI path never imports ``webui_app``):
#   L1 — shape-based regex (Bearer / authorization: Basic / key=value).
#   L2 — known-credential exact-value matching (reads the operator's configured
#        credential files and masks exact occurrences — catches short/oddly
#        shaped pasted tokens L1 cannot recognise).
#   L3 — entropy-based detection of long high-entropy runs (>= 32 chars,
#        Shannon entropy > 4.5), the blind spot the WebUI sanitizer documents.
# L2/L3 only run when ``redact`` is True.
_SCRUB_RE = re.compile(
    r"""(?ix)
    (?:
        bearer\s+[A-Za-z0-9\-._~+/]+=*          # Bearer <token>
      | authorization\s*:\s*\S+(?:\s+\S+)?      # authorization: <scheme> <token>
      | \b(?:token|secret|password|api_key|access_token|refresh_token
            |id_token|client_secret|integration_token|cookie|storage_state
            |hpassword|auth_response|challenge|form_body|post_data|formhash|sid)
        \s*[=:]\s*['\"]?[^\s'\"<>]+['\"]?       # key=value / key: value
    )
    """
)

# Long high-entropy runs worth masking even without a key name (L3).
_ENTROPY_RE = re.compile(r"[A-Za-z0-9\-._~+/=]{32,}")

# Cap pathological input before regex work (L3 scans every char).
_MAX_SCRUB_CHARS = 200_000

# Credential-file suffixes whose *values* are secret-equivalent (reused from
# ``cli.ops.health_check``'s audit list so the two views agree on what's a
# credential file).
_CREDENTIAL_SUFFIXES = (
    "-state.json",
    "-token.json",
    "-cookies.json",
    ".key",
    "-storage-state.json",
)


def _shannon_entropy(s: str) -> float:
    """Shannon entropy (bits/char) of ``s``."""
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    entropy = 0.0
    for c in counts.values():
        p = c / n
        entropy -= p * _math.log2(p)
    return entropy


def _json_string_leaves(obj: Any, depth: int = 0) -> list[str]:
    """Recursively collect string leaf values from a parsed JSON blob."""
    if depth > 6:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out: list[str] = []
        for v in obj.values():
            out.extend(_json_string_leaves(v, depth + 1))
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for v in obj:
            out.extend(_json_string_leaves(v, depth + 1))
        return out
    return []


def _known_secret_values() -> frozenset[str]:
    """Best-effort set of the operator's actual configured credential values.

    Reproduces the WebUI sanitizer's Layer 3 (exact known-value matching) for
    the core CLI path: read each credential file in the config dir and collect
    long, non-path/url string values (whole-file opaque tokens, or JSON string
    leaves). Cached per process. Never raises.
    """
    cache = getattr(_known_secret_values, "_cache", None)
    if cache is not None:
        return cache
    secrets: set[str] = set()
    try:
        config_dir = _config_dir()
        if config_dir.exists():
            for f in config_dir.iterdir():
                if not f.is_file() or not f.name.endswith(_CREDENTIAL_SUFFIXES):
                    continue
                try:
                    data = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                candidates: list[str] = []
                try:
                    candidates.extend(_json_string_leaves(json.loads(data)))
                except (ValueError, TypeError):
                    candidates.append(data)
                for c in candidates:
                    c = c.strip()
                    if len(c) >= 12 and "/" not in c and not c.startswith("http"):
                        secrets.add(c)
    except Exception:  # noqa: BLE001 — best-effort
        pass
    result: frozenset[str] = frozenset(secrets)
    _known_secret_values._cache = result  # type: ignore[attr-defined]
    return result


def _scrub_text(text: str, *, redact: bool = True) -> str:
    """Mask sensitive value shapes inside unstructured text (best-effort).

    L1 (shape regex) always runs. L2 (known-credential exact match) and L3
    (entropy) run only when ``redact`` is True — the ``--no-redact`` escape
    hatch skips all three.
    """
    if not text:
        return text
    if len(text) > _MAX_SCRUB_CHARS:
        text = text[-_MAX_SCRUB_CHARS:]

    def _mask_shape(m: re.Match[str]) -> str:
        tok = m.group(0)
        if re.match(r"(?i)bearer\s", tok):
            # Mask everything after the first whitespace following "Bearer".
            return tok.split(None, 1)[0] + " ***"
        if re.match(r"(?i)authorization\s*:", tok):
            # Mask the entire authorization value (incl. "Basic <token>").
            return re.sub(r"(:\s*).*", r"\1***", tok)
        return re.sub(r"(=\s*['\"]?|:\s*)\S+", r"\1***", tok)

    text = _SCRUB_RE.sub(_mask_shape, text)
    if redact:
        # L2: exact known-credential values.
        for secret in _known_secret_values():
            if secret and secret in text:
                text = text.replace(secret, "***")
        # L3: long high-entropy runs.
        text = _ENTROPY_RE.sub(
            lambda m: "***" if _shannon_entropy(m.group(0)) > 4.5 else m.group(0),
            text,
        )
    return text


@dataclass
class ReportInput:
    """Everything the operator (or WebUI) supplies about the failure."""

    envelope: ErrorEnvelope | None = None
    stderr_text: str = ""
    command: str | None = None
    run_id: str | None = None
    describe: str | None = None


# ---------------------------------------------------------------------------
# Section builders (each best-effort: a failure here degrades one section,
# never the whole report).
# ---------------------------------------------------------------------------


def _safe(fn: Any, default: Any) -> Any:
    """Run ``fn``; on any exception return ``default`` tagged for the report."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — best-effort section capture
        return {"_capture_error": f"{type(exc).__name__}: {exc}"}


def _git_available() -> bool:
    """Cache whether ``git`` is installed, so we skip the spawn entirely when
    it isn't (avoids a slow/failing subprocess on bare machines)."""
    cached = getattr(_git_available, "_cache", None)
    if cached is not None:
        return cached
    try:
        ok = (
            subprocess.run(
                ["git", "--version"], capture_output=True, text=True, timeout=2
            ).returncode == 0
        )
    except Exception:  # noqa: BLE001 — git optional
        ok = False
    _git_available._cache = ok  # type: ignore[attr-defined]
    return ok


def build_env_snapshot() -> dict[str, Any]:
    """OS / Python / package / paths / git / env-var names (no values)."""
    from importlib.metadata import PackageNotFoundError, version
    import platform

    pkg_version = "unknown"
    try:
        pkg_version = version("backlink-publisher")
    except PackageNotFoundError:
        pkg_version = "unknown (editable/untagged install)"

    env_names = sorted(os.environ.keys())
    # Audit finding [05]: NAMES ONLY. BACKLINK_/BLP_ env vars routinely hold
    # secrets (BACKLINK_LLM_API_KEY, BACKLINK_PROXY with inline creds, ...), and
    # _redact_in_place cannot mask them — it matches exact sensitive keys, not
    # full prefixed names. The report is advertised as safe-to-share and
    # config_echo surfaces these as names/set/unset only. Emit names, not values.
    blp_var_names = [
        k
        for k in env_names
        if k.startswith("BLP_") or k.startswith("BACKLINK_")
    ]

    git_branch = "unknown"
    git_sha = "unknown"
    if _git_available():
        try:
            git_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip() or "unknown"
            git_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip() or "unknown"
        except Exception:  # noqa: BLE001 — git optional
            git_branch = git_sha = "unknown"

    return {
        "os": os.name,
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "package_version": pkg_version,
        "config_dir": str(_config_dir()),
        "cache_dir": str(_cache_dir()),
        "git_branch": git_branch,
        "git_sha": git_sha,
        "env_var_count": len(env_names),
        "backlink_env_vars": blp_var_names,
        "env_var_names": env_names,
    }


def build_config_snapshot() -> dict[str, Any]:
    """Config-dir file *names* + credential permission audit (no contents)."""
    config_dir = _config_dir()
    file_names: list[str] = []
    try:
        if config_dir.exists():
            file_names = sorted(p.name for p in config_dir.iterdir() if p.is_file())
    except OSError:
        file_names = []

    creds = _safe(lambda: _check_all(str(config_dir), str(_cache_dir()))["credentials"], {})
    return {
        "config_dir": str(config_dir),
        "file_count": len(file_names),
        "file_names": file_names,
        "credential_audit": creds,
    }


def build_health() -> dict[str, Any]:
    """Storage health (mirrors ``health-check``)."""
    result: dict[str, Any] = _safe(
        lambda: _check_all(str(_config_dir()), str(_cache_dir())), {}
    )
    return result


def build_recent_runs(limit: int = _RECENT_RUNS_LIMIT) -> list[dict[str, Any]]:
    """Summarize the most recent checkpoint runs (no item payloads)."""
    try:
        runs = checkpoint.list_all_runs()[:limit]
    except Exception:  # noqa: BLE001 — checkpoint read is best-effort
        return []
    summaries: list[dict[str, Any]] = []
    for run in runs:
        items = run.get("items", []) or []
        summaries.append(
            {
                "run_id": run.get("run_id"),
                "started_at": run.get("started_at"),
                "platform": run.get("platform"),
                "mode": run.get("mode"),
                "pending": sum(1 for i in items if i.get("status") == "pending"),
                "failed": sum(1 for i in items if i.get("status") == "failed"),
                "resume_cmd": f"resume {run.get('run_id')}" if run.get("run_id") else None,
            }
        )
    return summaries


# ---------------------------------------------------------------------------
# Error section + self-diagnosis
# ---------------------------------------------------------------------------

_DIAGNOSIS: dict[str, list[str]] = {
    "AuthExpiredError": [
        "Channel credentials expired — re-bind the channel.",
        "Run the matching login command (e.g. `velog-login`, `medium-login`, `frw-login`) or use `bind-channel` in the WebUI.",
        "After re-binding, retry the original command; do NOT treat this as a code bug.",
    ],
    "ContentRejectedError": [
        "Server accepted auth but rejected the content — credentials are fine.",
        "Inspect the cited debug artifact and fix the underlying content (validation, rate-limit, slug collision).",
        "Re-binding the channel will NOT help; focus on the content.",
    ],
    "BannerUploadError": [
        "Media/banner upload failed (media-API problem, not auth).",
        "If `config.image_gen.strict` is false the row still publishes without the banner; check the image generator.",
    ],
    "AntiBotChallengeError": [
        "The site served an anti-bot interstitial (Cloudflare/CAPTCHA) to a well-formed request.",
        "This is a service-side block, not a credential problem — retry later or solve the challenge manually.",
    ],
    "DependencyError": [
        "A user action is required (install a tool, re-bind a credential, rebuild a config).",
        "Read the message for the exact missing precondition; resolve it, then re-run.",
    ],
    "ExternalServiceError": [
        "The external service was reachable but rejected/errored, or was unreachable.",
        "Often transient — retry after a short wait; if persistent, check the target URL/API status.",
    ],
    "UsageError": [
        "Bad CLI usage — review the command's `--help` and the argument that triggered this.",
    ],
    "InputValidationError": [
        "Input data failed validation — check the input file/args against the expected schema.",
    ],
    "RegistryError": [
        "Internal adapter-registry contract violation (programmer bug, not user input).",
        "Report this to the maintainers with this bundle; do not try to 'fix' config.",
    ],
    "InternalError": [
        "Unexpected internal error — likely a bug.",
        "Hand this bundle to a coding agent; include the stderr tail below.",
    ],
}


def self_diagnose(error_class: str | None) -> list[str]:
    """Return remediation hints for ``error_class`` (exact or family name)."""
    if not error_class:
        return ["No typed error was captured — describe the symptom in the report and include repro steps."]
    if error_class in _DIAGNOSIS:
        return _DIAGNOSIS[error_class]
    # Family fallback: anything ending in 'Error' under PipelineError.
    return [
        f"Untyped/unknown error class `{error_class}`.",
        "Hand this bundle to a coding agent with the stderr tail and repro steps.",
    ]


_RUN_ID_RE = re.compile(r"\brun_id=(\S+)")


def _extract_run_id(text: str) -> str | None:
    """Pull a ``run_id=...`` token out of raw stderr (best-effort)."""
    m = _RUN_ID_RE.search(text or "")
    return m.group(1) if m else None


def infer_error_class(stderr_text: str) -> str | None:
    """Heuristically guess a ``PipelineError`` subclass from raw stderr when no
    typed ``__BLP_ERR__`` envelope is present. Returns the class name or None.

    Order matters: an explicit class name printed in the text wins (highest
    precision), then a keyword/pattern heuristic over the lowered text.
    """
    if not stderr_text:
        return None
    for name in (
        "AuthExpiredError",
        "ContentRejectedError",
        "AntiBotChallengeError",
        "ExternalServiceError",
        "DependencyError",
        "UsageError",
        "InputValidationError",
        "RegistryError",
        "BannerUploadError",
    ):
        if name in stderr_text:
            return name
    lowered = stderr_text.lower()
    patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("AuthExpiredError", ("credential expired", "cookie expired", "token expired", "auth expired", "rebind", "re-bind")),
        ("ContentRejectedError", ("content rejected", "content was rejected", "slug collision")),
        ("AntiBotChallengeError", ("cloudflare", "captcha", "anti-bot", "challenge")),
        ("ExternalServiceError", ("rate limit", "rate-limit", "ratelimit", "403 forbidden", "502", "503", "504", "timed out", "connection refused", "unreachable")),
        ("DependencyError", ("missing dependency", "not installed", "please install", "precondition")),
        ("UsageError", ("usage:", "unrecognized arguments", "invalid choice", "argument required")),
        ("InputValidationError", ("validation failed", "invalid input", "schema")),
    )
    for cls, keys in patterns:
        if any(k in lowered for k in keys):
            return cls
    return None


def build_error_section(inp: ReportInput, *, redact: bool = True) -> dict[str, Any]:
    """Typed error + redacted stderr tail. Parses the envelope from stderr if
    one was not supplied directly, else infers the class heuristically.
    Free-text scrubbing is skipped when ``redact`` is False (the ``--no-redact``
    escape hatch)."""
    envelope = inp.envelope or parse_envelope(inp.stderr_text)
    inferred: str | None = None
    if envelope is None and inp.stderr_text:
        inferred = infer_error_class(inp.stderr_text)
    raw_tail = inp.stderr_text if not redact else _scrub_text(inp.stderr_text)
    stderr_tail = raw_tail.splitlines()[-_STDERR_TAIL_LINES:]

    error_class = (
        envelope.error_class
        if envelope
        else (inp.envelope.error_class if inp.envelope else (inferred or "unknown"))
    )
    section: dict[str, Any] = {
        "captured": envelope is not None or bool(inp.stderr_text.strip()),
        "inferred": inferred is not None and envelope is None,
        "error_class": error_class,
        "exit_code": envelope.exit_code if envelope else None,
        "message": (
            _scrub_text(envelope.message) if (redact and envelope) else (envelope.message if envelope else None)
        ),
        "stderr_tail": stderr_tail,
        "stderr_tail_truncated": len(inp.stderr_text.splitlines()) > _STDERR_TAIL_LINES,
    }
    return section


# ---------------------------------------------------------------------------
# Assembly + rendering
# ---------------------------------------------------------------------------


def build_report(inp: ReportInput, *, redact: bool = True) -> dict[str, Any]:
    """Assemble the full report dict from a :class:`ReportInput`."""
    error_section = _safe(lambda: build_error_section(inp, redact=redact), {})
    run_id = inp.run_id or _extract_run_id(inp.stderr_text)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "schema": "blp-bug-report/1",
        "command": inp.command,
        "run_id": run_id,
        "description": (_scrub_text(inp.describe) if (redact and inp.describe) else inp.describe),
        "error": error_section,
        "environment": _safe(build_env_snapshot, {}),
        "config_snapshot": _safe(build_config_snapshot, {}),
        "health": _safe(build_health, {}),
        "recent_runs": _safe(lambda: build_recent_runs(), []),
        "suggested_fixes": self_diagnose(
            error_section.get("error_class") if isinstance(error_section, dict) else None
        ),
    }
    if redact:
        # Defense-in-depth: walk every structured section for sensitive keys.
        _redact_in_place(report)
    return report


def render_json(report: dict[str, Any]) -> str:
    """Machine-readable JSON rendering of the report."""
    return json.dumps(report, ensure_ascii=False, indent=2)


def _md_section(title: str, body: str) -> str:
    return f"## {title}\n\n{body}\n"


def render_markdown(report: dict[str, Any]) -> str:
    """Coding-agent-friendly Markdown rendering."""
    err = report.get("error", {}) or {}
    env = report.get("environment", {}) or {}
    cfg = report.get("config_snapshot", {}) or {}
    health = report.get("health", {}) or {}

    lines: list[str] = []
    lines.append("# Backlink-Publisher 錯誤回報 (Bug Report)")
    lines.append("")
    lines.append(f"- 產生時間: `{report.get('generated_at')}`")
    if report.get("run_id"):
        lines.append(f"- run_id: `{report.get('run_id')}`")
    if report.get("command"):
        lines.append(f"- 原始指令: `{report.get('command')}`")
    desc = report.get("description")
    lines.append(f"- 使用者描述: {desc or '(未提供)'}")
    lines.append("")

    # TL;DR
    tldr = "無法判定（無錯誤來源）"
    if err.get("error_class") and err.get("error_class") != "unknown":
        tldr = f"{err.get('error_class')} (exit {err.get('exit_code')})"
    lines.append(_md_section("TL;DR", f"錯誤類型：**{tldr}**"))

    # Repro
    repro = "- 原始指令: `" + (report.get("command") or "(未提供)") + "`\n"
    if report.get("run_id"):
        repro += f"- 續跑指令: `resume {report.get('run_id')}`\n"
    repro += "- 重現步驟: (請補充 — 做了什麼、預期結果、實際結果)\n"
    lines.append(_md_section("重現步驟 (Repro)", repro))

    # Error
    err_body = f"- error_class: `{err.get('error_class')}`\n"
    err_body += f"- exit_code: `{err.get('exit_code')}`\n"
    if err.get("message"):
        err_body += f"- message:\n\n```\n{err.get('message')}\n```\n"
    tail = err.get("stderr_tail") or []
    if tail:
        tail_text = "\n".join(tail)
        err_body += f"- stderr 末 {len(tail)} 行（已去敏）:\n\n```\n{tail_text}\n```\n"
    lines.append(_md_section("錯誤 (Error)", err_body))

    # Environment
    env_lines = [f"- os: `{env.get('os')}`", f"- platform: `{env.get('platform')}`",
                f"- python: `{env.get('python_version')}`", f"- package: `{env.get('package_version')}`",
                f"- config_dir: `{env.get('config_dir')}`", f"- cache_dir: `{env.get('cache_dir')}`",
                f"- git: `{env.get('git_branch')}` @ `{env.get('git_sha')}`",
                f"- env_var_count: `{env.get('env_var_count')}`"]
    blp = env.get("backlink_env_vars") or []
    if blp:
        env_lines.append("- backlink env vars (names only):")
        for k in blp:
            env_lines.append(f"    - `{k}`")
    lines.append(_md_section("環境 (Environment)", "\n".join(env_lines) + "\n"))

    # Config snapshot
    cfg_lines = [f"- config_dir: `{cfg.get('config_dir')}`", f"- file_count: `{cfg.get('file_count')}`"]
    names = cfg.get("file_names") or []
    if names:
        cfg_lines.append("- files:")
        for n in names:
            cfg_lines.append(f"    - `{n}`")
    creds = cfg.get("credential_audit") or {}
    if creds:
        cfg_lines.append(
            f"- credential audit: {creds.get('total')} files, "
            f"{creds.get('non_0600')} non-0600"
        )
    lines.append(_md_section("設定快照 (Config Snapshot, 去敏)", "\n".join(cfg_lines) + "\n"))

    # Health
    health_body = _render_health(health)
    lines.append(_md_section("儲存體健康 (Health)", health_body))

    # Recent runs
    runs = report.get("recent_runs") or []
    if runs:
        run_lines = ["| run_id | started | platform | mode | pending | failed |",
                     "|---|---|---|---|---|---|"]
        for r in runs:
            run_lines.append(
                f"| `{r.get('run_id')}` | {r.get('started_at')} | {r.get('platform')} | "
                f"{r.get('mode')} | {r.get('pending')} | {r.get('failed')} |"
            )
        lines.append(_md_section("近期執行 (Recent Runs)", "\n".join(run_lines) + "\n"))
    else:
        lines.append(_md_section("近期執行 (Recent Runs)", "_（無）_\n"))

    # Suggested fixes
    fixes = report.get("suggested_fixes") or []
    fixes_body = "\n".join(f"{i+1}. {f}" for i, f in enumerate(fixes)) + "\n"
    lines.append(_md_section("建議修復 (Suggested Fixes)", fixes_body))

    # Machine-readable JSON
    lines.append(_md_section("機器可讀 JSON", f"```json\n{render_json(report)}\n```\n"))

    return "\n".join(lines)


def _render_health(health: dict[str, Any]) -> str:
    """Compact human view of the health dict (already non-sensitive)."""
    if not health or health.get("_capture_error"):
        return f"_（無法取得：{health.get('_capture_error', 'unknown')}）_\n"
    out: list[str] = []
    for key in ("events_db", "dedup_db"):
        db = health.get(key) or {}
        name = key.replace("_", ".")
        if db.get("error"):
            out.append(f"- {name}: ERROR — {db['error']}")
        elif not db.get("exists"):
            out.append(f"- {name}: not found")
        else:
            out.append(f"- {name}: {db.get('size_mb')} MB, {db.get('rows')} rows")
    cd = health.get("config_dir") or {}
    out.append(f"- config: {cd.get('file_count')} files @ {cd.get('path')}")
    creds = health.get("credentials") or {}
    out.append(f"- credentials: {creds.get('total')} files, {creds.get('non_0600')} non-0600")
    cp = health.get("checkpoints") or {}
    if cp.get("exists"):
        out.append(f"- checkpoints: {cp.get('count')} files, oldest {cp.get('age_hours')}h")
    else:
        out.append("- checkpoints: (none)")
    return "\n".join(out) + "\n"


def save_report(
    report: dict[str, Any], output_dir: str | Path, *, redact: bool = True
) -> tuple[Path, Path]:
    """Write the report to ``<output_dir>/<timestamp>-<slug>.md`` (+ ``.json``).

    Both files are written 0600 (owner-only) because even redacted paths can
    leak the operator's username / directory layout. Returns (md_path, json_path).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    slug_src = report.get("run_id") or report.get("error", {}).get("error_class") or "general"
    slug = re.sub(r"[^0-9A-Za-z_-]", "-", str(slug_src))[:40] or "general"
    base = out / f"{stamp}-{slug}"

    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    md_text = render_markdown(report)
    json_text = render_json(report)

    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")
    try:
        md_path.chmod(0o600)
        json_path.chmod(0o600)
    except OSError:
        pass  # best-effort; Windows may ignore chmod
    return md_path, json_path
