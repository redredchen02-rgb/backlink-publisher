"""YAML catalog schema for config-driven lightweight publisher adapters (U1).

Each catalog entry encodes a single publishing platform as data — no Python
subclass needed. The validated entry is consumed by ConfigDrivenAdapter (U2)
and used to auto-generate a ``register()`` call (U3).

Schema fields (``VALID_TOP_LEVEL_KEYS``):
  slug              str          Platform identifier, matches filename
  endpoint          str          Submit URL (form-POST or API endpoint)
  auth_type         str          ``none`` | ``api_key_header`` | ``api_key_query``
  content_field     str          Form/JSON field name for the article body
  csrf_prefetch     bool         Whether to GET form page before POST (default false)
  csrf_field_names  list[str]    Hidden field names to extract on prefetch
  permalink_via     str          ``redirect`` | ``json_path`` | ``regex``
  permalink_arg     str          JSONPath / regex pattern / ``Location`` header hint
  min_delay_s       float        Minimum seconds between publishes (default 0)
  dofollow          bool|str     ``true`` | ``false`` | ``uncertain``
  rationale         str          Required >= 80 stripped chars when dofollow != true
  referral_value    str          ``high`` | ``low`` (required when dofollow != true)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


# ── Valid value sets ──────────────────────────────────────────────────────────

VALID_AUTH_TYPES: tuple[str, ...] = ("none", "api_key_header", "api_key_query")
VALID_DOFOLLOW: tuple[Any, ...] = (True, False, "uncertain")
VALID_REFERRAL: tuple[str, ...] = ("high", "low")
VALID_PERMALINK_VIA: tuple[str, ...] = ("redirect", "json_path", "regex")

VALID_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "slug", "endpoint", "auth_type", "content_field",
    "csrf_prefetch", "csrf_field_names",
    "permalink_via", "permalink_arg",
    "min_delay_s",
    "dofollow", "rationale", "referral_value",
})

_MIN_RATIONALE_CHARS: int = 80


# ── Error type ────────────────────────────────────────────────────────────────

class CatalogValidationError(ValueError):
    """Raised when a catalog entry fails schema validation."""


# ── Validation ────────────────────────────────────────────────────────────────

def validate_entry(data: dict[str, Any], source: str = "<unknown>") -> dict[str, Any]:
    """Validate a parsed catalog entry dict against the schema.

    Returns a cleaned dict with defaults filled. Raises
    ``CatalogValidationError`` on any violation with a message identifying
    the source file and field.
    """
    errors: list[str] = []

    # -- Required strings --------------------------------------------------
    slug = data.get("slug")
    if not slug or not isinstance(slug, str):
        errors.append("slug: required string")

    endpoint = data.get("endpoint")
    if not endpoint or not isinstance(endpoint, str):
        errors.append("endpoint: required string")

    auth_type = data.get("auth_type", "none")
    if auth_type not in VALID_AUTH_TYPES:
        errors.append(
            f"auth_type: must be one of {VALID_AUTH_TYPES}, got {auth_type!r}"
        )

    content_field = data.get("content_field")
    if not content_field or not isinstance(content_field, str):
        errors.append("content_field: required string")

    permalink_via = data.get("permalink_via")
    if permalink_via not in VALID_PERMALINK_VIA:
        errors.append(
            f"permalink_via: must be one of {VALID_PERMALINK_VIA}, "
            f"got {permalink_via!r}"
        )

    permalink_arg = data.get("permalink_arg")
    if not permalink_arg or not isinstance(permalink_arg, str):
        errors.append("permalink_arg: required string")

    # -- Dofollow gate (mirrors ``register()`` contract) -------------------
    dofollow = data.get("dofollow")
    if dofollow not in VALID_DOFOLLOW:
        errors.append(
            f"dofollow: must be true / false / 'uncertain', "
            f"got {dofollow!r}"
        )

    if dofollow is not True:
        rationale = data.get("rationale")
        stripped_len = len(rationale.strip()) if isinstance(rationale, str) else 0
        if stripped_len < _MIN_RATIONALE_CHARS:
            errors.append(
                f"rationale: required string >= {_MIN_RATIONALE_CHARS} stripped chars "
                f"when dofollow != true (got {stripped_len})"
            )
        referral_value = data.get("referral_value")
        if referral_value not in VALID_REFERRAL:
            errors.append(
                f"referral_value: must be one of {VALID_REFERRAL} when "
                f"dofollow != true, got {referral_value!r}"
            )

    # -- Optional booleans / lists / numbers --------------------------------
    csrf_prefetch = data.get("csrf_prefetch", False)
    if csrf_prefetch not in (True, False):
        errors.append("csrf_prefetch: must be a boolean")

    csrf_field_names = data.get("csrf_field_names")
    if csrf_field_names is not None:
        if not isinstance(csrf_field_names, list) or not all(
            isinstance(n, str) for n in csrf_field_names
        ):
            errors.append("csrf_field_names: must be a list of strings")

    min_delay_s = data.get("min_delay_s", 0.0)
    if not isinstance(min_delay_s, (int, float)) or min_delay_s < 0:
        errors.append("min_delay_s: must be a non-negative number")

    # -- Reject unknown keys -----------------------------------------------
    for key in data:
        if key not in VALID_TOP_LEVEL_KEYS:
            errors.append(f"unknown key: {key!r}")

    if errors:
        raise CatalogValidationError(
            f"{source}: {len(errors)} validation error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return {
        "slug": slug,
        "endpoint": endpoint,
        "auth_type": auth_type,
        "content_field": content_field,
        "csrf_prefetch": csrf_prefetch,
        "csrf_field_names": csrf_field_names or [],
        "permalink_via": permalink_via,
        "permalink_arg": permalink_arg,
        "min_delay_s": min_delay_s,
        "dofollow": dofollow,
        "rationale": data.get("rationale", ""),
        "referral_value": data.get("referral_value", ""),
    }


# ── Catalog dir scanning & loading ────────────────────────────────────────────

def discover_catalog_dirs(
    built_in: str = "",
    user_dir: str = "",
) -> list[Path]:
    """Return ordered list of catalog dir paths to scan.

    Built-in dir is scanned first; user dir overlays by slug (last wins).
    """
    dirs: list[Path] = []
    if built_in:
        p = Path(built_in)
        if p.is_dir():
            dirs.append(p)
    if user_dir:
        p = Path(user_dir)
        if p.is_dir():
            dirs.append(p)
    return dirs


def load_catalog_yaml(path: Path) -> dict[str, Any] | None:
    """Load and parse a single catalog YAML file via ``yaml.safe_load``.

    Returns ``None`` for empty files. Raises ``CatalogValidationError`` on
    YAML parse errors (this enforces ``safe_load`` only — ``!!python/object``
    tags cannot be resolved by ``safe_load`` and raise ``yaml.YAMLError``,
    which is wrapped).
    """
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise CatalogValidationError(f"{path}: YAML parse error: {e}")
    return parsed


def load_entries_from_dir(catalog_dir: Path) -> dict[str, dict[str, Any]]:
    """Load and validate all ``.yaml`` / ``.yml`` files in a catalog dir.

    Returns a dict mapping slug → validated entry. Duplicate slugs from
    later files overwrite earlier ones (user-overlay semantics).
    """
    entries: dict[str, dict[str, Any]] = {}
    for yaml_path in sorted(catalog_dir.glob("*.yaml")) + sorted(
        catalog_dir.glob("*.yml")
    ):
        parsed = load_catalog_yaml(yaml_path)
        if parsed is None:
            continue  # empty file
        if not isinstance(parsed, dict):
            raise CatalogValidationError(
                f"{yaml_path}: expected mapping at top level, "
                f"got {type(parsed).__name__}"
            )
        for slug, entry_data in parsed.items():
            if not isinstance(entry_data, dict):
                raise CatalogValidationError(
                    f"{yaml_path}[{slug!r}]: expected mapping, "
                    f"got {type(entry_data).__name__}"
                )
            entry_data["slug"] = slug
            validated = validate_entry(entry_data, source=f"{yaml_path}[{slug!r}]")
            entries[slug] = validated
    return entries


def load_all_entries(
    built_in_dir: str = "",
    user_config_dir: str = "",
) -> dict[str, dict[str, Any]]:
    """Load catalog entries from built-in then user dir (user slugs win)."""
    entries: dict[str, dict[str, Any]] = {}
    for catalog_dir in discover_catalog_dirs(built_in_dir, user_config_dir):
        entries.update(load_entries_from_dir(catalog_dir))
    return entries
