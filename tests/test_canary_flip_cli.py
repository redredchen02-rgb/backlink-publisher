"""F2 (plan 2026-07-13-004): canary-flip promotion automation (completes U11).

Turns a confirmed canary verdict into edits that flip a dofollow="uncertain"
adapter to dofollow=True — flipping the register() flag, dropping the
rationale=/referral_value= kwargs, removing the multi-line _R entry, and marking
the canary-pending.md row 'flipped'. Respects A5: default emits a patch; the
module never commits. ast.parse guards every generated source.
"""

from __future__ import annotations

import ast

import pytest

from backlink_publisher._util.errors import UsageError
from backlink_publisher.cli.spray.canary_flip import (
    flip_tracker_row,
    plan_flip,
    render_patch,
)

# A realistic slice of publishing/adapters/__init__.py (two register blocks).
INIT_SRC = '''    register(
        "txtfyi",
        TxtfyiFormPostAdapter,
        dofollow="uncertain",  # R4 canary pending; Phase 0 preliminary = dofollow
        rationale=_R["txtfyi"],
        referral_value="low",  # anonymous pastebin; modest DA + R4 pending
        **TXTFYI_MANIFEST,
    )
    register(
        "notesio",
        NotesioFormPostAdapter,
        dofollow="uncertain",  # R4 canary pending; 3rd-party probe 12/0 dofollow
        rationale=_R["notesio"],
        referral_value="low",  # anonymous pastebin; modest DA + R4 pending
        **NOTESIO_MANIFEST,
    )
'''

# A realistic slice of _nofollow_rationales.py (multi-line parenthesized entries
# whose string bodies themselves contain parens like "register()").
RATIONALES_SRC = '''_R = {
    "txtfyi": (
        "Registered dofollow=uncertain pending the R4 canary loop "
        "(Plan 2026-05-25-001 Unit 7): confirmed only by publishing a canary "
        "and reading verify_link_attributes, then amending register() to True."
    ),
    "notesio": (
        "notes.io: dofollow confirmed 12/0 on 3rd-party posts; server-rendered "
        "static HTML, no rel=nofollow. Pending OUR-pipeline canary."
    ),
}
'''


def test_plan_flip_sets_true_and_strips_kwargs():
    edits = plan_flip(INIT_SRC, RATIONALES_SRC, "txtfyi", date="2026-07-13")
    # register block for txtfyi flipped
    assert "dofollow=True,  # OUR canary 2026-07-13: dofollow confirmed" in edits.new_init
    assert 'rationale=_R["txtfyi"]' not in edits.new_init
    # both blocks had an identical referral_value line; only txtfyi's is dropped (2 -> 1)
    assert edits.new_init.count('referral_value="low"') == 1
    assert "**TXTFYI_MANIFEST" in edits.new_init  # manifest splat untouched
    # notesio block completely untouched
    assert 'dofollow="uncertain",  # R4 canary pending; 3rd-party probe' in edits.new_init
    assert 'rationale=_R["notesio"]' in edits.new_init
    # _R entry for txtfyi removed (multi-line), notesio kept
    assert '"txtfyi":' not in edits.new_rationales
    assert '"notesio":' in edits.new_rationales
    # the rationales module (a full module) stays valid Python after removal
    ast.parse(edits.new_rationales)
    # the flipped register block is valid Python when embedded in a function body
    ast.parse("def register_all():\n" + edits.new_init)


def test_plan_flip_refuses_platform_without_block():
    with pytest.raises(UsageError):
        plan_flip(INIT_SRC, RATIONALES_SRC, "wordpresscom")


def test_plan_flip_refuses_when_block_not_uncertain():
    already_true = INIT_SRC.replace('dofollow="uncertain",  # R4 canary pending; Phase 0 preliminary = dofollow',
                                    "dofollow=True,")
    with pytest.raises(UsageError):
        plan_flip(already_true, RATIONALES_SRC, "txtfyi")


def test_flip_tracker_row_marks_flipped():
    tracker = (
        "<!-- canary-pending:begin -->\n"
        "| platform | registered | deadline | status |\n"
        "|---|---|---|---|\n"
        "| txtfyi | 2026-05-25 | 2026-07-25 | pending |\n"
        "| notesio | 2026-06-03 | 2026-09-01 | pending |\n"
        "<!-- canary-pending:end -->\n"
    )
    out = flip_tracker_row(tracker, "txtfyi")
    assert "| txtfyi | 2026-05-25 | 2026-07-25 | flipped |" in out
    assert "| notesio | 2026-06-03 | 2026-09-01 | pending |" in out  # others untouched


def test_render_patch_is_unified_diff():
    patch = render_patch("a/b.py", "x = 1\n", "x = 2\n")
    assert patch.startswith("--- a/a/b.py")
    assert "-x = 1" in patch and "+x = 2" in patch


def test_main_default_writes_patch_against_real_registry(tmp_path, monkeypatch):
    """End-to-end on the real __init__.py: default mode writes a reviewable patch,
    never mutates source, and the flipped result ast-parses (validated in main)."""
    import json

    receipt = tmp_path / "verdict.jsonl"
    receipt.write_text(
        json.dumps({"platform": "txtfyi", "verdict": "dofollow"}) + "\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    import backlink_publisher.cli.spray.canary_flip as canary_flip
    with pytest.raises(SystemExit) as exc:
        canary_flip.main(["txtfyi", "--from-receipt", str(receipt)])
    assert exc.value.code == 0

    patch = (tmp_path / "canary-flip-txtfyi.patch").read_text(encoding="utf-8")
    assert "dofollow=True" in patch
    assert '-        dofollow="uncertain"' in patch
    assert "canary-pending.md" in patch  # tracker row updated too (source checkout)


def test_main_refuses_nofollow_verdict(tmp_path, monkeypatch):
    import json

    receipt = tmp_path / "verdict.jsonl"
    receipt.write_text(
        json.dumps({"platform": "txtfyi", "verdict": "nofollow"}) + "\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    import backlink_publisher.cli.spray.canary_flip as canary_flip
    with pytest.raises(SystemExit) as exc:
        canary_flip.main(["txtfyi", "--from-receipt", str(receipt)])
    assert exc.value.code == 1
    assert not (tmp_path / "canary-flip-txtfyi.patch").exists()
