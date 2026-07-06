"""Enforce debt_registry.toml format and content quality.

Schema rules enforced:
  - TOML file exists and parses at repo root
  - Contains a non-empty [[items]] array
  - Each item has all 6 required fields: slug, severity, rationale, discovered, owner, status
  - Each rationale >= 80 characters
  - Each severity is one of low/medium/high/critical
  - Each status is one of open/mitigated/accepted/resolved
  - resolved_date is REQUIRED for status resolved/mitigated, FORBIDDEN for open/accepted,
    and must be a valid ISO date when present (so closing a debt is never silent)
  - All slugs are unique

D2b (plan 2026-06-30-001) structural anti-gaming additions — NOT a text-
similarity check. An earlier design called for a `difflib.SequenceMatcher`
reason-similarity check; adversarial review actually computed it and found
it fails in both directions (0.488 for two genuinely-duplicate vague
excuses, 0.934 for two genuinely-distinct valid reasons). See
tests/test_seam_except_classification.py's module docstring for the full
history. D2b replaces that with three structural rules instead:
  - `location` field: array of "path/to/file.py:<line_number>" strings,
    required iff the entry's slug is referenced by a `# debt: <slug>`
    comment anywhere in src/ or webui_app/ (see debt_registry.toml's header
    comment for the full field contract)
  - every (slug, location) pair across the whole registry must be unique
  - no two entries may share a byte-for-byte identical `rationale` string
  - a cross-reference scan of the same six seam directories C1b's AST
    scanner covers (events/, gap/, idempotency/, ledger/, _util/,
    webui_app/api/) confirms every `# debt: <slug>` comment there has a
    registry entry whose `location` includes that comment's own file:line
"""
from __future__ import annotations

__tier__ = "unit"
from pathlib import Path
import re
import tomllib

import pytest

# tests/ is not a package — import the shared debt-comment format constant
# from conftest.py rather than redefining our own regex, per C1b's explicit
# "don't let the two units' code silently drift" instruction (see
# conftest.py's "Seam-layer debt-comment format" section).
from conftest import DEBT_COMMENT_RE  # type: ignore[import]

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_FILE = REPO_ROOT / "debt_registry.toml"
RATIONALE_MIN_CHARS = 80
MIN_ITEMS = 5
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_STATUSES = {"open", "mitigated", "accepted", "resolved"}
REQUIRED_FIELDS = {"slug", "severity", "rationale", "discovered", "owner", "status"}
OPTIONAL_FIELDS = {"resolved_date", "location"}
# resolved_date must be present iff status is in this set
STATUS_REQUIRES_RESOLVED_DATE = {"resolved", "mitigated"}
# A `location` entry must look like "some/relative/path.py:123".
_LOCATION_ENTRY_RE = re.compile(r"^[\w./\-]+\.py:\d+$")

REGISTRY = tomllib.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
ITEMS = REGISTRY.get("items", [])

# ── D2b scan roots ───────────────────────────────────────────────────────────
# Codebase-wide scan (excluding tests/) used to decide whether a slug's
# `location` field is required at all — plan action 1 says "referenced by a
# `# debt: <slug>` comment anywhere in the codebase", which is broader than
# C1b's six seam directories (e.g. cli/_dedup_gate.py and
# webui_app/helpers/contexts.py carry `# debt:` comments but sit outside
# C1b's scan roots).
_LOCATION_REQUIRED_SCAN_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "src",
    REPO_ROOT / "webui_app",
)

# The exact six seam directories C1b's AST scanner covers
# (test_seam_except_classification.py). D2b's cross-reference test
# deliberately mirrors this scope — the plan's one explicit shared alignment
# point between the two units.
_SEAM_SCAN_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "src" / "backlink_publisher" / "events",
    REPO_ROOT / "src" / "backlink_publisher" / "gap",
    REPO_ROOT / "src" / "backlink_publisher" / "idempotency",
    REPO_ROOT / "src" / "backlink_publisher" / "ledger",
    REPO_ROOT / "src" / "backlink_publisher" / "_util",
    REPO_ROOT / "webui_app" / "api",
)


def _scan_debt_comments(roots: tuple[Path, ...]) -> dict[str, list[tuple[str, int]]]:
    """slug -> [(relpath, lineno), ...] for every `# debt: <slug>` comment under roots."""
    refs: dict[str, list[tuple[str, int]]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                m = DEBT_COMMENT_RE.search(line)
                if m:
                    refs.setdefault(m.group("slug"), []).append((rel, lineno))
    return refs


ALL_CODE_DEBT_REFS = _scan_debt_comments(_LOCATION_REQUIRED_SCAN_ROOTS)
SEAM_DEBT_REFS = _scan_debt_comments(_SEAM_SCAN_ROOTS)


# ── D2b checker functions ────────────────────────────────────────────────────
# Factored out of the ITEMS-bound test bodies so the red-path self-tests below
# can exercise them against small synthetic fixtures, independent of the real
# debt_registry.toml (mirrors test_seam_except_classification.py's pattern of
# testing the scanner logic directly rather than only the live-repo result).


def _find_slug_location_duplicates(items: list[dict]) -> list[tuple[str, str]]:
    """(slug, location) entries where `location` is already claimed elsewhere.

    NOTE on why this checks `location` value uniqueness across the WHOLE
    registry, not just within a matching slug: `slug` is already required
    globally unique by test_all_slugs_unique, so two DIFFERENT [[items]]
    entries can never legitimately share a slug. That means a literal
    "(slug, location) tuple" duplicate could only ever arise from the same
    slug's own `location` array repeating one entry twice — a narrow,
    almost-accidental case. The plan's actual anti-gaming scenario ("two
    different call points' `# debt:` comments point to the same location")
    is broader: a single source line can only ever carry one `# debt:
    <slug>` comment, so if the SAME location string is claimed by two
    entries with DIFFERENT slugs, at least one of those claims is false.
    Checking location-value uniqueness across all entries (regardless of
    slug) catches both shapes and is what gives "(slug, location) pair
    uniqueness" real teeth given the slug-uniqueness constraint.
    """
    claimed_by: dict[str, str] = {}
    dupes: list[tuple[str, str]] = []
    for item in items:
        slug = item.get("slug", "?")
        for loc in item.get("location", []):
            if loc in claimed_by:
                dupes.append((slug, loc))
            else:
                claimed_by[loc] = slug
    return dupes


def _find_exact_duplicate_rationales(items: list[dict]) -> list[tuple[str, str]]:
    """(first_slug, dupe_slug) pairs sharing a byte-identical rationale string."""
    seen: dict[str, str] = {}
    dupes: list[tuple[str, str]] = []
    for item in items:
        rationale = item.get("rationale", "")
        slug = item.get("slug", "?")
        if rationale in seen:
            dupes.append((seen[rationale], slug))
        else:
            seen[rationale] = slug
    return dupes


def _find_cross_reference_mismatches(
    items: list[dict], debt_refs: dict[str, list[tuple[str, int]]]
) -> list[tuple[str, str]]:
    """(slug, "path.py:N") for every code comment with no matching registry location."""
    by_slug_locations: dict[str, set[str]] = {}
    for item in items:
        slug = item.get("slug")
        by_slug_locations.setdefault(slug, set()).update(item.get("location", []))

    missing: list[tuple[str, str]] = []
    for slug, sites in debt_refs.items():
        registered = by_slug_locations.get(slug, set())
        for rel, lineno in sites:
            expected = f"{rel}:{lineno}"
            if expected not in registered:
                missing.append((slug, expected))
    return missing


def test_registry_file_exists_and_parses() -> None:
    """The registry file must exist at repo root and parse as valid TOML."""
    assert REGISTRY_FILE.exists(), f"{REGISTRY_FILE} not found at repo root"
    assert isinstance(REGISTRY, dict), "debt_registry.toml did not parse to a dict"


def test_registry_has_non_empty_items() -> None:
    """The registry must contain a non-empty [[items]] array."""
    assert "items" in REGISTRY, "debt_registry.toml missing top-level [[items]]"
    assert isinstance(ITEMS, list), "debt_registry.toml 'items' must be an array"
    assert len(ITEMS) >= MIN_ITEMS, (
        f"debt_registry.toml has {len(ITEMS)} items, "
        f"minimum is {MIN_ITEMS}"
    )


def test_all_slugs_unique() -> None:
    """Every [[items]] entry must have a unique slug."""
    slugs = [item["slug"] for item in ITEMS]
    duplicates = {s for s in slugs if slugs.count(s) > 1}
    assert not duplicates, (
        f"Duplicate slug(s) found: {duplicates}. "
        f"Each slug must be unique."
    )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_item_has_required_fields(idx: int) -> None:
    """Each item must have all 6 required fields and no unknown fields."""
    item = ITEMS[idx]
    missing = REQUIRED_FIELDS - set(item.keys())
    assert not missing, (
        f"Item {idx} (slug={item.get('slug', 'UNKNOWN')}) "
        f"missing required field(s): {missing}"
    )
    extra = set(item.keys()) - REQUIRED_FIELDS - OPTIONAL_FIELDS
    assert not extra, (
        f"Item {idx} (slug={item.get('slug', 'UNKNOWN')}) "
        f"has unknown field(s): {extra}. "
        f"Allowed: required={sorted(REQUIRED_FIELDS)}, optional={sorted(OPTIONAL_FIELDS)}"
    )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_resolved_date_presence_matches_status(idx: int) -> None:
    """resolved_date must be present iff status is resolved/mitigated.

    Closing a debt (resolved/mitigated) without a timestamp is silent; an
    open/accepted item carrying a resolved_date is contradictory. Both are
    rejected so the registry stays an honest signal.
    """
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    status = item.get("status", "")
    has_date = "resolved_date" in item
    needs_date = status in STATUS_REQUIRES_RESOLVED_DATE
    if needs_date and not has_date:
        pytest.fail(
            f"Item '{slug}' status={status!r} requires a 'resolved_date' field "
            f"(YYYY-MM-DD) to record when the debt was closed."
        )
    if not needs_date and has_date:
        pytest.fail(
            f"Item '{slug}' status={status!r} must NOT carry a 'resolved_date' "
            f"(only resolved/mitigated items may)."
        )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_resolved_date_format_when_present(idx: int) -> None:
    """When present, resolved_date must be a valid ISO date (YYYY-MM-DD)."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    resolved_date = item.get("resolved_date")
    if resolved_date is None:
        return
    parts = resolved_date.split("-")
    assert len(parts) == 3, (
        f"Item '{slug}' resolved_date={resolved_date!r} is not YYYY-MM-DD"
    )
    year, month, day = parts
    assert year.isdigit() and len(year) == 4, (
        f"Item '{slug}' resolved_date={resolved_date!r} has invalid year"
    )
    assert month.isdigit() and 1 <= int(month) <= 12, (
        f"Item '{slug}' resolved_date={resolved_date!r} has invalid month"
    )
    assert day.isdigit() and 1 <= int(day) <= 31, (
        f"Item '{slug}' resolved_date={resolved_date!r} has invalid day"
    )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_field_types_are_strings(idx: int) -> None:
    """Each required field must be a non-empty string."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    for field in REQUIRED_FIELDS:
        val = item.get(field)
        assert isinstance(val, str), (
            f"Item '{slug}' field '{field}' must be str, "
            f"got {type(val).__name__}"
        )
        assert len(val) > 0, (
            f"Item '{slug}' field '{field}' must not be empty"
        )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_rationale_length(idx: int) -> None:
    """Each rationale must be >= 80 characters."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    rationale = item.get("rationale", "")
    n = len(rationale)
    assert n >= RATIONALE_MIN_CHARS, (
        f"Item '{slug}' rationale length {n} < {RATIONALE_MIN_CHARS} minimum. "
        f"Expand the rationale to explain why this debt exists and its context."
    )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_severity_valid(idx: int) -> None:
    """Each severity must be one of low/medium/high/critical."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    severity = item.get("severity", "")
    assert severity in VALID_SEVERITIES, (
        f"Item '{slug}' severity={severity!r} is not valid. "
        f"Must be one of {sorted(VALID_SEVERITIES)}"
    )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_status_valid(idx: int) -> None:
    """Each status must be one of open/mitigated/accepted/resolved."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    status = item.get("status", "")
    assert status in VALID_STATUSES, (
        f"Item '{slug}' status={status!r} is not valid. "
        f"Must be one of {sorted(VALID_STATUSES)}"
    )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_discovered_date_format(idx: int) -> None:
    """Each discovered date must be a valid ISO date (YYYY-MM-DD)."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    discovered = item.get("discovered", "")
    parts = discovered.split("-")
    assert len(parts) == 3, (
        f"Item '{slug}' discovered={discovered!r} is not YYYY-MM-DD"
    )
    year, month, day = parts
    assert year.isdigit() and len(year) == 4, (
        f"Item '{slug}' discovered={discovered!r} has invalid year"
    )
    assert month.isdigit() and 1 <= int(month) <= 12, (
        f"Item '{slug}' discovered={discovered!r} has invalid month"
    )
    assert day.isdigit() and 1 <= int(day) <= 31, (
        f"Item '{slug}' discovered={discovered!r} has invalid day"
    )


def test_no_stale_mitigated_items() -> None:
    """Mitigated items whose resolved_date is >90 days ago must be re-evaluated.

    A mitigated item that has sat unreviewed for 90+ days is a registry lie:
    either the residual work is done (upgrade to resolved) or the debt is
    actively accepted (change to accepted with updated rationale). This test
    enforces the freshness pass that resolves the debt-registry-staleness debt item.
    """
    import datetime

    today = datetime.date.today()
    stale = []
    for item in ITEMS:
        if item.get("status") != "mitigated":
            continue
        rd = item.get("resolved_date", "")
        try:
            rd_date = datetime.date.fromisoformat(rd)
        except (ValueError, TypeError):
            continue
        age_days = (today - rd_date).days
        if age_days > 90:
            stale.append((item.get("slug", "?"), rd, age_days))

    assert not stale, (
        "Stale mitigated items detected (>90 days since resolved_date). "
        "Either upgrade to 'resolved' or change to 'accepted' with updated rationale:\n"
        + "\n".join(f"  slug={s}  resolved_date={d}  age={a}d" for s, d, a in stale)
    )


# ── D2b: location field + structural anti-gaming tests ──────────────────────


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_location_field_type_when_present(idx: int) -> None:
    """When present, `location` must be a non-empty array of "path.py:N" strings."""
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    if "location" not in item:
        return
    loc = item["location"]
    assert isinstance(loc, list) and loc, (
        f"Item '{slug}' location must be a non-empty array, got {loc!r}"
    )
    for entry in loc:
        assert isinstance(entry, str), (
            f"Item '{slug}' location entries must be strings, got {entry!r}"
        )
        assert _LOCATION_ENTRY_RE.match(entry), (
            f"Item '{slug}' location entry {entry!r} must match "
            f"'path/to/file.py:<line_number>'"
        )


@pytest.mark.parametrize("idx", range(len(ITEMS)))
def test_location_required_when_referenced_by_debt_comment(idx: int) -> None:
    """`location` is required iff the slug is referenced by a `# debt:` comment.

    Plan D2b action 1: retrofitting `location` is conditional, not universal —
    older registry-only entries (e.g. ko-corpus-calibration) that predate any
    `# debt: <slug>` code comment correctly have no `location` field.
    """
    item = ITEMS[idx]
    slug = item.get("slug", f"item-{idx}")
    if slug in ALL_CODE_DEBT_REFS:
        assert "location" in item, (
            f"Item '{slug}' is referenced by a `# debt: {slug}` comment in "
            f"the codebase at {ALL_CODE_DEBT_REFS[slug]} but has no "
            f"`location` field."
        )


def test_slug_location_pairs_unique() -> None:
    """No `location` value may be claimed by more than one [[items]] entry.

    D2b's core anti-gaming rule (plan action 2): each call site must be
    backed by exactly one (slug, location) pair. Since `slug` is already
    globally unique (test_all_slugs_unique), this test's real teeth is
    catching two DIFFERENT slugs both claiming the same call site — a single
    source line can only carry one `# debt: <slug>` comment, so that shape
    always means at least one registry entry's `location` is wrong.
    """
    dupes = _find_slug_location_duplicates(ITEMS)
    assert not dupes, (
        f"location value(s) claimed by more than one debt_registry.toml entry: "
        f"{dupes}. Each call site (location) may be claimed by exactly one entry."
    )


def test_no_exact_duplicate_rationale() -> None:
    """No two entries may share a byte-for-byte identical `rationale` string.

    D2b action 6: deliberately exact string equality, not fuzzy similarity —
    catches the cheapest copy-paste-without-editing regression path only.
    """
    dupes = _find_exact_duplicate_rationales(ITEMS)
    assert not dupes, (
        f"Byte-identical `rationale` strings shared by entries: {dupes}. "
        f"Each debt entry must have its own distinct rationale text."
    )


def test_cross_reference_debt_comments_have_registry_entries() -> None:
    """Every `# debt: <slug>` comment in the six seam dirs must resolve to a
    debt_registry.toml entry whose `location` includes that comment's own
    file:line (plan D2b action 3, scope matches C1b's AST scanner exactly).
    """
    missing = _find_cross_reference_mismatches(ITEMS, SEAM_DEBT_REFS)
    assert not missing, (
        "`# debt: <slug>` comment(s) found with no matching debt_registry.toml "
        f"(slug, location) entry: {missing}. Either add/extend the registry "
        f"entry's `location` array to include the comment's file:line, or "
        f"the comment references the wrong slug."
    )


# ── D2b red-path self-tests ───────────────────────────────────────────────────
# Mirrors test_seam_except_classification.py's self-test pattern: exercise the
# checker FUNCTIONS against small synthetic fixtures, proving the guardrails
# have teeth independent of the real (currently clean) debt_registry.toml.


def test_red_path_slug_location_duplicate_is_detected() -> None:
    # Same slug, same location repeated across two entries (degenerate case —
    # can't happen alongside a live slug-uniqueness rule except within one
    # entry's own array, but the checker still catches it).
    dupes = [
        {"slug": "foo", "location": ["a.py:1"]},
        {"slug": "foo", "location": ["a.py:1"]},
    ]
    assert _find_slug_location_duplicates(dupes) == [("foo", "a.py:1")]

    # The actual plan scenario: two DIFFERENT call points (different slugs)
    # whose entries both claim the same location. A single source line can
    # only carry one `# debt: <slug>` comment, so this is always a real
    # violation — at least one of the two entries' `location` is wrong.
    cross_slug_dupes = [
        {"slug": "foo", "location": ["a.py:1"]},
        {"slug": "bar", "location": ["a.py:1"]},
    ]
    assert _find_slug_location_duplicates(cross_slug_dupes) == [("bar", "a.py:1")]

    clean = [
        {"slug": "foo", "location": ["a.py:1"]},
        {"slug": "foo", "location": ["a.py:2"]},
    ]
    assert _find_slug_location_duplicates(clean) == []


def test_red_path_exact_duplicate_rationale_is_detected() -> None:
    dupes = [
        {"slug": "a", "rationale": "identical text padded to eighty-plus characters for the check"},
        {"slug": "b", "rationale": "identical text padded to eighty-plus characters for the check"},
    ]
    assert _find_exact_duplicate_rationales(dupes) == [("a", "b")]

    clean = [
        {"slug": "a", "rationale": "distinct text one padded to eighty-plus characters for the check"},
        {"slug": "b", "rationale": "distinct text two padded to eighty-plus characters for the check"},
    ]
    assert _find_exact_duplicate_rationales(clean) == []


def test_red_path_cross_reference_missing_location_is_detected() -> None:
    items = [{"slug": "foo", "location": ["a.py:1"]}]
    # A second, unregistered call site for the same slug.
    debt_refs = {"foo": [("a.py", 1), ("a.py", 99)]}
    assert _find_cross_reference_mismatches(items, debt_refs) == [("foo", "a.py:99")]

    # Fully covered: no mismatch.
    debt_refs_ok = {"foo": [("a.py", 1)]}
    assert _find_cross_reference_mismatches(items, debt_refs_ok) == []
