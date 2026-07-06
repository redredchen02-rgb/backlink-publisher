"""C1b — seam-layer bare `except Exception:` AST scanner〔R5〕.

Plan 2026-06-30-001, unit C1b (see the "C1b —" subsection for full doc-review
history). This test is a pure AST scanner + self-test, NOT a reason-similarity
checker: an earlier design called for a `difflib.SequenceMatcher`-based
"reason text >90% similar = duplicate" check, but adversarial review actually
computed it and found it fails in both directions (0.488 similarity for two
genuinely-duplicate vague excuses; 0.934 for two genuinely-distinct valid
reasons). That approach was rejected; the duplicate-detection problem is
tracked separately under unit D2b (debt_registry.toml location-binding),
which has not run yet as of this file's creation.

Mirrors the `tests/test_events_r8_gates.py` pattern: an AST scan of specific
seam modules, plus a red-path self-test proving the gate has teeth.

KNOWN LIMITATION (intentionally not solved by this scanner — see plan C1b
action 3): this only catches a LITERAL bare `except Exception:` or fully
bare `except:`. If someone narrows the type to something specific (e.g.
`except (OSError, ValueError):`) WITHOUT adding a `# debt: <slug>` comment —
mirroring the exact anti-pattern D2 found and fixed in
`events/reconciler.py`, `gap/events_gap.py`, and `webui_app/helpers/contexts.py`
— the AST shape here no longer matches `ast.Name(id="Exception")` or a bare
`except:`, so this scanner cannot see it. Extending detection to cover
"narrowed but unclassified" in general is materially higher design
complexity (it would need to reason about whether a narrowing was ever
reviewed) and is deferred to a future iteration; the known existing
instances of that pattern were reviewed and fixed by hand in D2, not by this
guardrail.
"""
from __future__ import annotations

__tier__ = "unit"

import ast
from pathlib import Path
import re

# tests/ is not a package — import shared constants from conftest.py,
# mirroring test_no_raw_home_path_primitives.py's GRANDFATHERED_EXPANDUSER_SITES
# import.
from conftest import DEBT_COMMENT_RE  # type: ignore[import]

_REPO_ROOT = Path(__file__).resolve().parents[1]

# The six seam directories in scope (plan C1b action 1). `_util/` is
# explicitly included per doc-review — it matches D2's Batch 1 priority, and
# without it D2's `_util/` classification work would have no regression
# guard at all.
_SCAN_ROOTS: tuple[Path, ...] = (
    _REPO_ROOT / "src" / "backlink_publisher" / "events",
    _REPO_ROOT / "src" / "backlink_publisher" / "gap",
    _REPO_ROOT / "src" / "backlink_publisher" / "idempotency",
    _REPO_ROOT / "src" / "backlink_publisher" / "ledger",
    _REPO_ROOT / "src" / "backlink_publisher" / "_util",
    _REPO_ROOT / "webui_app" / "api",
)

# A "reason" other than a `# debt: <slug>` comment: an adjacent log/logger
# call inside the handler's own span. Matches both attribute-call style
# (`plan_logger.error(...)`, `_log.exception(...)`, `log.warning(...)`) and
# direct-call style (`_log_recon_event(...)`). This is an implementation
# heuristic of THIS scanner only — unlike DEBT_COMMENT_RE, it is not a format
# shared with D2/D2b, so it stays local rather than living in conftest.py.
_LOG_CALL_RE = re.compile(r"\b\w*log\w*\s*\.\s*\w+\s*\(|\b\w*log\w*\s*\(")


def _is_bare_except_exception(handler: ast.ExceptHandler) -> bool:
    """True for a fully bare `except:` or a literal `except Exception:`.

    Deliberately does NOT match tuple types (`except (Exception,):`) or any
    narrowed type — see the module docstring's known limitation.
    """
    return handler.type is None or (
        isinstance(handler.type, ast.Name) and handler.type.id == "Exception"
    )


def _handler_span(handler: ast.ExceptHandler) -> tuple[int, int]:
    """The (start, end) 1-indexed line range owned by this handler alone.

    Critical correctness requirement (plan C1b action 2): this must be
    bound to the handler's OWN AST node line range, never a fixed-offset
    window — `webui_app/helpers/contexts.py` has back-to-back try/except
    blocks with no blank line between them, where a fixed "look N lines"
    window would misattribute a neighboring handler's reason comment (see
    the red-path self-test below for the regression shape this guards
    against). ``end_lineno`` is populated by the parser from the handler's
    own body, so it never spills into a sibling or outer handler's lines.
    """
    start = handler.lineno
    end = getattr(handler, "end_lineno", None) or start
    return start, end


def _reason_in_span(lines: list[str], start: int, end: int) -> str | None:
    """Return a reason marker if the handler's own span documents itself.

    Checked, in the handler's own line range only:
      * a `# debt: <slug>` comment (returns ``"debt:<slug>"``), or
      * an adjacent log/logger call (returns ``"log-call"``).
    Returns None if neither is present anywhere in [start, end].
    """
    span_text = "\n".join(lines[start - 1 : end])
    m = DEBT_COMMENT_RE.search(span_text)
    if m:
        return f"debt:{m.group('slug')}"
    if _LOG_CALL_RE.search(span_text):
        return "log-call"
    return None


def _bare_except_findings(source: str) -> list[tuple[int, str | None]]:
    """(lineno, reason_or_None) for every bare except handler in ``source``."""
    tree = ast.parse(source)
    lines = source.splitlines()
    findings: list[tuple[int, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_bare_except_exception(node):
            start, end = _handler_span(node)
            findings.append((node.lineno, _reason_in_span(lines, start, end)))
    return findings


def _unclassified_lines(source: str) -> list[int]:
    """Line numbers of bare excepts in ``source`` with no reason found."""
    return [ln for ln, reason in _bare_except_findings(source) if reason is None]


def _iter_scanned_py_files():
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        yield from sorted(root.rglob("*.py"))


def _discover_unclassified_sites() -> frozenset[tuple[str, int]]:
    """Live scan of the six seam roots for unclassified bare excepts."""
    sites: set[tuple[str, int]] = set()
    for path in _iter_scanned_py_files():
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Unreadable file — skip rather than crash the whole scan; a
            # file this scanner can't even read can't hide a violation any
            # differently than one it can read but that has no violations.
            continue
        try:
            unclassified = _unclassified_lines(source)
        except SyntaxError:
            # Unparseable file — same rationale as above.
            continue
        if not unclassified:
            continue
        rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
        sites.update((rel, ln) for ln in unclassified)
    return frozenset(sites)


# ── Grandfathered allowlist (plan C1b action 6) ──────────────────────────────
#
# Mirrors `GRANDFATHERED_EXPANDUSER_SITES` in conftest.py: shrink-only,
# frozen at the moment this scanner landed. C1b lands after D2 but D2 did
# not reach literal 100% coverage of every bare `except Exception:` in the
# six scan roots above (D2's own scope was framed as "the known instances");
# without this allowlist, this scanner would red-line CI immediately for
# every PR from the moment it lands, not just for genuinely NEW violations.
#
# Frozen 2026-07-02 via a live run of THIS FILE's own `_discover_unclassified_sites()`
# (not a hand-maintained grep) against the six scan roots, immediately after
# D2 completed. Each entry below is a bare `except Exception:` with neither
# a `# debt: <slug>` comment nor an adjacent log/logger call inside its own
# handler span:
#
#   * idempotency/audit_log.py — the `_current_user()` best-effort
#     `getpass.getuser()` fallback has a `# pragma: no cover` comment but no
#     `# debt:`/log call.
#   * ledger/aggregate.py — a `canonicalize_url()` failure inside the
#     latest-verdict scan loop has only a `# noqa: BLE001` comment.
#
# Plan 2026-07-06-002 D3 closed the `events/_project_helpers.py` pair (the
# sqlite3.IntegrityError fallback path's two nested bare excepts) by adding
# `# debt: project-helpers-ensure-article-fallback-degrade-accepted` comments
# + a matching debt_registry.toml entry — removed from the allowlist below
# per this docstring's own instruction.
#
# D2 (or a follow-up debt pass) should close these incrementally by adding a
# `# debt: <slug>` comment + matching debt_registry.toml entry and removing
# the corresponding line below — never add a NEW entry to grandfather a
# freshly introduced violation; that always means fix it or classify it.
GRANDFATHERED_BARE_EXCEPT_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        ("src/backlink_publisher/idempotency/audit_log.py", 45),
        ("src/backlink_publisher/ledger/aggregate.py", 68),
    }
)


def test_no_new_unclassified_bare_except_in_seam_modules():
    """R5: only pre-existing, explicitly-grandfathered bare excepts may pass.

    Shrink-only enforcement: the live-discovered set must be a subset of (or
    exactly equal to) the frozen allowlist above. A newly introduced,
    unclassified bare `except Exception:` in any of the six scan roots fails
    this test — it is not silently absorbed into the allowlist.
    """
    discovered = _discover_unclassified_sites()
    new_violations = sorted(discovered - GRANDFATHERED_BARE_EXCEPT_SITES)
    assert not new_violations, (
        "New unclassified bare `except Exception:` (or fully bare `except:`) "
        f"found in seam modules: {new_violations}. Add a `# debt: <slug>` "
        "comment (with a matching debt_registry.toml entry) or a log/logger "
        "call inside the handler — do not add it to "
        "GRANDFATHERED_BARE_EXCEPT_SITES, which is shrink-only."
    )
    assert discovered <= GRANDFATHERED_BARE_EXCEPT_SITES


def test_red_path_bare_except_is_detected():
    """Proves the scanner has teeth on the three shapes doc-review named.

    (a) an isolated bare except with no reason — the base case.
    (b) back-to-back try/except blocks with no code between them, reason
        comments attached in BOTH directions (before and after an
        unclassified handler) — proves attribution never bleeds across to a
        neighboring handler, the exact real shape found in
        `webui_app/helpers/contexts.py` that motivated action 2.
    (c) a nested try/except — proves the inner handler is scoped to its own
        (small) span and does not inherit the outer handler's reason
        comment, which lies outside the inner handler's own line range.
    """
    # (a) isolated bare except, no reason anywhere.
    isolated = "\n".join(
        [
            "def f():",
            "    try:",
            "        risky()",
            "    except Exception:",
            "        pass",
        ]
    )
    assert _unclassified_lines(isolated) == [4]

    # (b) four back-to-back try/except blocks, zero blank lines between
    # them. Handler A (line 4) and handler D (line 17) each have their own
    # `# debt:` comment; handlers B (line 9) and C (line 13) have none.
    # A naive fixed-line-offset scanner could misattribute A's or D's
    # comment to its bare neighbor; the AST-span-bound scanner must not.
    back_to_back = "\n".join(
        [
            "def f():",
            "    try:",
            "        a()",
            "    except Exception:",  # line 4 — handler A, has its own reason
            "        # debt: reason-a",
            "        pass",
            "    try:",
            "        b()",
            "    except Exception:",  # line 9 — handler B, no reason
            "        pass",
            "    try:",
            "        c()",
            "    except Exception:",  # line 13 — handler C, no reason
            "        pass",
            "    try:",
            "        d()",
            "    except Exception:",  # line 17 — handler D, has its own reason
            "        # debt: reason-d",
            "        pass",
        ]
    )
    assert _unclassified_lines(back_to_back) == [9, 13]

    # (c) nested try/except: inner handler (line 5) is bare with no reason
    # of its own; outer handler (line 7) has a `# debt:` comment that lies
    # entirely outside the inner handler's own [5, 6] span.
    nested = "\n".join(
        [
            "def f():",
            "    try:",
            "        try:",
            "            inner()",
            "        except Exception:",  # line 5 — inner handler, no reason
            "            pass",
            "    except Exception:",  # line 7 — outer handler, has its own reason
            "        # debt: reason-outer",
            "        pass",
        ]
    )
    assert _unclassified_lines(nested) == [5]

    # Sanity: a classified isolated handler (either form) is NOT flagged.
    classified_via_debt = "\n".join(
        [
            "def f():",
            "    try:",
            "        risky()",
            "    except Exception:",
            "        # debt: some-reason",
            "        pass",
        ]
    )
    assert _unclassified_lines(classified_via_debt) == []

    classified_via_log = "\n".join(
        [
            "def f():",
            "    try:",
            "        risky()",
            "    except Exception:",
            "        logger.warning('failed: %s', 'x')",
            "        pass",
        ]
    )
    assert _unclassified_lines(classified_via_log) == []

    # A fully bare `except:` (no type at all) is caught the same way as a
    # literal `except Exception:`.
    fully_bare = "\n".join(
        [
            "def f():",
            "    try:",
            "        risky()",
            "    except:",
            "        pass",
        ]
    )
    assert _unclassified_lines(fully_bare) == [4]

    # A narrowed except is explicitly OUT of this scanner's shape (see the
    # module docstring's known limitation) — even with no reason at all, it
    # must not be flagged here.
    narrowed = "\n".join(
        [
            "def f():",
            "    try:",
            "        risky()",
            "    except (OSError, ValueError):",
            "        pass",
        ]
    )
    assert _unclassified_lines(narrowed) == []
