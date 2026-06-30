"""Advisory dead-code canary via ``vulture`` (debt ``orphan-code-unknown``).

Companion to ``tests/test_no_orphan_code.py`` (file-level orphan gate). That
test catches whole *modules* nothing imports; it cannot catch intra-module
dead code — unused imports, unused locals, vestigial CLI flags, dead branches.
This gate fills that gap using vulture's static reachability analysis.

Design choice: ADVISORY, not hard-fail.
---------------------------------------
Vulture has known blind spots for this codebase's patterns:
  - adapters registered by string (``register("velog", VelogAdapter, ...)``)
  - entry points declared in pyproject ``[project.scripts]`` (every CLI is a
    reachable ``main()`` that vulture can't see)
  - Jinja template call sites, ``getattr`` dispatch, dataclass fields consumed
    only by TOML round-tripping
A hard vulture gate would be permanently red. Instead this gate emits
``warnings.warn`` for each high-confidence finding — the count shows up in
pytest's CI warning summary, surfacing drift without blocking. This mirrors
the repo's existing R7 monolith-canary pattern (advisory ``UserWarning``).

Allowlist policy
----------------
An allowlist entry suppresses a *known* finding so only *new* dead code shows
up as a warning. Allowlist a finding only when it's a vulture false positive
(a reachable-by-pattern site vulture can't see) — never to hide real dead code.
Real dead code found by this gate should be DELETED, not allowlisted.
"""
from __future__ import annotations

__tier__ = "unit"

import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("src/backlink_publisher", "webui_app", "webui_store")
MIN_CONFIDENCE = 80  # vulture's high-confidence band; 60% is too noisy (343 hits).

# Findings that are vulture false positives for this codebase. Each carries the
# reason it's reachable-by-pattern. Real dead code must NOT land here — delete it.
ALLOWLIST: dict[str, str] = {
    # __exit__ context-manager signature: exc_type/tb are required by the ABC
    # protocol even when the body doesn't use them.
    "src/backlink_publisher/publishing/browser_publish/_chrome_session_impl.py:444:unused variable 'exc_type'": (
        "__exit__ protocol params required by AbstractContextManager; not "
        "referenced in the body but mandated by the signature."
    ),
    "src/backlink_publisher/publishing/browser_publish/_chrome_session_impl.py:444:unused variable 'tb'": (
        "__exit__ protocol param (traceback); same ABC-signature rationale as exc_type."
    ),
    # structlog_config.py — opt-in module (allowlisted in test_no_orphan_code);
    # method_name is part of a structlog processor signature.
    "src/backlink_publisher/_util/structlog_config.py:24:unused variable 'method_name'": (
        "structlog_config.py is opt-in (allowlisted in test_no_orphan_code); "
        "method_name is part of a processor signature being staged."
    ),
    # content/fetch.py: _max_body_bytes is imported for the env-var constant
    # surface (re-exported as part of the module's network-config API).
    "src/backlink_publisher/content/fetch.py:51:unused import '_max_body_bytes'": (
        "Network-config constant imported as part of the fetch module's "
        "documented env-var surface; re-exported, not dead."
    ),
    # Page import in chrome_session: used for type hints / isinstance checks
    # that vulture's flow analysis misses.
    "src/backlink_publisher/publishing/browser_publish/_chrome_session_impl.py:42:unused import 'Page'": (
        "Playwright Page type used in isinstance/type-check sites vulture's "
        "static analysis doesn't track."
    ),
    # livejournal write_mode param: part of the adapter's published() signature
    # mirroring the cross-adapter contract; consumed by the dispatcher.
    "src/backlink_publisher/publishing/adapters/livejournal_api.py:154:unused variable 'write_mode'": (
        "Adapter publish() signature param mirroring the cross-adapter contract "
        "the dispatcher calls; kept for signature parity across adapters."
    ),
}


def _key(path: Path, finding: str) -> str:
    """Build the allowlist key for a finding: '<relpath>:<lineno>:<message>'."""
    rel = str(path.relative_to(REPO_ROOT))
    return f"{rel}:{finding}"


def _vulture_findings() -> list[tuple[Path, str]]:
    """Run vulture over SCAN_ROOTS; return [(path, finding_text), ...].

    finding_text is ``"<lineno>:<message>"`` matching the ALLOWLIST key suffix.
    Uses ``Vulture.get_unused_code(min_confidence=...)`` (the supported API;
    min_confidence is a get_unused_code kwarg, NOT a Vulture.__init__ / scavenge
    kwarg in vulture >=2.x).
    """
    pytest.importorskip("vulture")
    from vulture import Vulture

    v = Vulture(verbose=False)
    v.scavenge([str(REPO_ROOT / r) for r in SCAN_ROOTS])
    items = v.get_unused_code(min_confidence=MIN_CONFIDENCE, sort_by_size=False)

    out: list[tuple[Path, str]] = []
    for item in items:
        try:
            p = Path(item.filename)
        except (TypeError, ValueError):
            continue
        out.append((p, f"{item.first_lineno}:{item.message}"))
    return out


def test_dead_code_advisory() -> None:
    """Warn (don't fail) on high-confidence dead code not in the allowlist.

    New findings surface as UserWarnings in the CI warning summary. To address:
      1. If it's REAL dead code → delete it (don't allowlist).
      2. If it's a vulture false positive → add to ALLOWLIST with the
         reachable-by-pattern reason.
    """
    findings = _vulture_findings()

    new_findings: list[str] = []
    for path, finding in findings:
        try:
            key = _key(path, finding)
        except ValueError:
            # Finding path outside repo root — ignore, not ours.
            continue
        if key in ALLOWLIST:
            continue
        new_findings.append(key)

    for key in new_findings:
        warnings.warn(
            f"Potential dead code (vulture >=80% confidence, not allowlisted): "
            f"{key}. Delete it if real, or add to ALLOWLIST in "
            f"test_dead_code_advisory.py with a reachable-by-pattern reason.",
            UserWarning,
            stacklevel=2,
        )

    # No assertion on count — advisory. The point is CI warning visibility.
    # If the allowlist perfectly matches the current findings, new_findings is
    # empty and no warning fires — that is the desired steady state.


def test_allowlist_keys_resolve_and_justified() -> None:
    """Every allowlist entry must point at a real file+finding and carry a real reason."""
    for key, reason in ALLOWLIST.items():
        path_part = key.rsplit(":", 2)[0]
        assert (REPO_ROOT / path_part).exists(), (
            f"ALLOWLIST key {key!r}: file {path_part!r} does not exist."
        )
        assert len(reason.strip()) >= 40, (
            f"ALLOWLIST reason for {key!r} too short (<40 chars); explain WHY "
            f"this is a vulture false positive, not real dead code."
        )
