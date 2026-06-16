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
"""
from __future__ import annotations

__tier__ = "unit"
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_FILE = REPO_ROOT / "debt_registry.toml"
RATIONALE_MIN_CHARS = 80
MIN_ITEMS = 5
VALID_SEVERITIES = {"low", "medium", "high", "critical"}
VALID_STATUSES = {"open", "mitigated", "accepted", "resolved"}
REQUIRED_FIELDS = {"slug", "severity", "rationale", "discovered", "owner", "status"}
OPTIONAL_FIELDS = {"resolved_date"}
# resolved_date must be present iff status is in this set
STATUS_REQUIRES_RESOLVED_DATE = {"resolved", "mitigated"}

REGISTRY = tomllib.loads(REGISTRY_FILE.read_text())
ITEMS = REGISTRY.get("items", [])


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
