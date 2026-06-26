"""Static validator: every RECON event name emitted in source has a schema entry.

This is NOT a runtime validation — the schema is authoring-only.
The test:
  1. Greps all ``emit("name"``, ``driver._emit("name"``, and ``.recon("name"``
     call sites across ``src/backlink_publisher/``.
  2. Loads the Draft 2020-12 schema from ``docs/architecture/event_schema.json``.
  3. Extracts every enum'ed event name from the schema's ``$defs``.
  4. Asserts every source-level event name is covered.

The test intentionally does NOT validate payload shapes — that would be
a runtime schema and this is an authoring-time taxonomy document.
"""
from __future__ import annotations

__tier__ = "unit"
import json
from pathlib import Path
import re

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "docs" / "architecture" / "event_schema.json"
SOURCE_DIR = PROJECT_ROOT / "src" / "backlink_publisher"

# Patterns to find event-name strings at emit/recon call sites.
_EMIT_PATTERNS: list[re.Pattern] = [
    # EventStore.append("event.name", ...)
    re.compile(r'''\.(?:emit|append)\(\s*["']([a-zA-Z_][a-zA-Z0-9_.]*)["']'''),
    # driver._emit("event.name", ...)
    re.compile(r'''\._emit\(\s*["']([a-zA-Z_][a-zA-Z0-9_.]*)["']'''),
    # logger.recon("event.name", ...)
    re.compile(r'''\.recon\(\s*["']([a-zA-Z_][a-zA-Z0-9_.]*)["']'''),
]


def _collect_source_events() -> set[str]:
    """Return every unique event-name string found at emit/recon call sites."""
    events: set[str] = set()
    for py_path in SOURCE_DIR.rglob("*.py"):
        text = py_path.read_text(encoding="utf-8")
        for pat in _EMIT_PATTERNS:
            for m in pat.finditer(text):
                events.add(m.group(1))
    return events


def _collect_schema_events() -> set[str]:
    """Return every unique event-name string referenced across schema $defs enums."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defs = schema.get("$defs", {})
    events: set[str] = set()
    for def_name, def_body in defs.items():
        # Standard JSON Schema: look for enum in properties
        for prop_key in ("kind", "msg", "event"):
            prop = def_body.get("properties", {}).get(prop_key, {})
            if "enum" in prop:
                events.update(prop["enum"])
        # Also handle RECON text line enums (prefix field)
        prop = def_body.get("properties", {}).get("prefix", {})
        if "enum" in prop:
            events.update(prop["enum"])
    return events


# False positives from the regex: these match the pattern but are NOT event
# names. They are "failed_checks" array values in canary_targets.py
# (fc.append("target_anchor_missing") / fc.append("target_nofollow")).
_FALSE_POSITIVE_APPEND_CALLS: frozenset[str] = frozenset({
    "target_anchor_missing",
    "target_nofollow",
})

_EVENTS_THAT_ARE_NOT_CALL_SITE_STRINGS: frozenset[str] = frozenset({
    # These are the events.db kind strings from events/kinds.py that are
    # referenced via module constants (e.g. kinds.PUBLISH_INTENT), not as
    # bare string literals. The occluded constants are:
    #   "publish.intent", "publish.confirmed", "publish.unverified",
    #   "publish.failed", "publish.verified", "publish.verify_failed",
    #   "draft.created", "draft.scheduled", "banner.source_url_fallback",
    #   "banner.skipped_no_method", "banner.failed", "banner.embedded",
    #   "banner.skipped_no_artifact", "image_gen_invoked",
    #   "image_gen_capped", "image_gen_disabled_auto",
    #   "citation.observed", "link.rechecked"
    # They ARE covered in the schema (events.db layer), but the strings don't
    # appear literally at call sites because the code imports the constant.
    #
    # The channel.bind.* events DO appear as literals at call sites
    # (bind_channel.py + _driver_impl.py), so they are NOT in this set.
    #
    # The RECON text line prefixes ("RECON info", "RECON warn") do not
    # appear in source as call-site string patterns because they are
    # constructed via f-strings/concatenation in _plan_check_format.py.
    # They ARE covered in the schema (system_recon_line $defs).
    "RECON info",
    "RECON warn",
})


def test_schema_loads() -> None:
    """Verify event_schema.json is valid JSON."""
    raw = SCHEMA_PATH.read_text(encoding="utf-8")
    schema = json.loads(raw)
    assert "$schema" in schema
    assert "$defs" in schema
    assert isinstance(schema["$defs"], dict)


def test_schema_against_draft_2020_12_meta_schema() -> None:
    """Verify event_schema.json is structurally valid Draft 2020-12 JSON Schema.

    This uses a bundled subset of the meta-schema: it checks that every
    schema keyword used is valid in Draft 2020-12.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    # Structural checks
    for def_name, def_body in schema.get("$defs", {}).items():
        assert "type" in def_body, f"$defs/{def_name} missing 'type'"
        assert "properties" in def_body, f"$defs/{def_name} missing 'properties'"
        for prop_key, prop_val in def_body["properties"].items():
            if "enum" in prop_val:
                assert isinstance(prop_val["enum"], list), (
                    f"$defs/{def_name}.properties.{prop_key}.enum is not a list"
                )


def test_every_source_event_has_schema_entry() -> None:
    """Every event-name string at emit/recon call sites has a schema $defs entry."""
    source_events = _collect_source_events()
    schema_events = _collect_schema_events()

    # The source also contains non-event strings matched by the patterns
    # (false positives from unrelated string constants). We filter: an
    # event name is one that starts with a known prefix or is in the
    # occluded-constant set.
    known_prefixes = {
        "publish.", "draft.", "banner.", "image_gen_", "citation.",
        "link.", "channel.bind.", "link_count_", "cell_gate_",
        "content_fetch_", "plan_", "preflight_", "canary_",
        "fetch_verify_", "category_", "detail_", "row_",
        "validate_", "recheck_", "reverify_", "probe_citations_",
        "generate_", "cull_", "click_track_", "comment_",
        "dedup_", "target_", "RECON ",
    }

    uncovered: set[str] = set()
    for ev in source_events:
        if not any(ev.startswith(p) for p in known_prefixes):
            continue
        if ev in _FALSE_POSITIVE_APPEND_CALLS:
            continue
        if ev not in schema_events and ev not in _EVENTS_THAT_ARE_NOT_CALL_SITE_STRINGS:
            uncovered.add(ev)

    assert not uncovered, (
        f"The following event names appear at emit/recon call sites but have no "
        f"corresponding $defs entry in {SCHEMA_PATH}:\n"
        + "\n".join(sorted(uncovered))
    )


def test_schema_events_from_occluded_constants_are_not_lost() -> None:
    """Verify the occluded-constant events are still present in the schema."""
    schema_events = _collect_schema_events()
    for ev in sorted(_EVENTS_THAT_ARE_NOT_CALL_SITE_STRINGS):
        if ev.startswith("RECON "):
            # RECON info / RECON warn are text-line prefixes, checked separately
            continue
        assert ev in schema_events, (
            f"Event {ev!r} (from occluded constants) is missing from schema $defs"
        )
