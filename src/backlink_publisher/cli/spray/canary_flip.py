"""canary-flip — turn a confirmed canary verdict into a ready-to-apply promotion.

Completes plan unit U11 (flip-or-kill). ``canary-seed`` produces a verdict
receipt (``verdict="dofollow"``) but promoting the platform was ~6 manual steps
of hand-editing ``publishing/adapters/__init__.py``. This tool performs that
transform mechanically:

  1. flip ``register("<p>", …, dofollow="uncertain", …)`` → ``dofollow=True``
  2. drop the now-unneeded ``rationale=`` / ``referral_value=`` kwargs
  3. remove the multi-line ``_R["<p>"]`` entry in ``_nofollow_rationales.py``
  4. mark the ``docs/discovery/canary-pending.md`` row ``flipped``

Rule **A5**: by default this NEVER edits the registry in place — it prints a
unified diff and writes a ``.patch`` for the operator to review + ``git apply``.
``--apply`` performs the working-tree edits after printing the diff, and never
commits. Every generated source is ``ast.parse``-validated; a malformed result
refuses (UsageError) rather than emitting a broken patch.

Contract: emits the diff on stdout; guidance on stderr; exit 0 on success.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import difflib
import json
from pathlib import Path
import sys
from typing import Any, cast

from backlink_publisher._util.errors import UsageError


@dataclass
class FlipEdits:
    new_init: str
    new_rationales: str


def _find_register_block(lines: list[str], platform: str) -> tuple[int, int]:
    """Return (start, end) line indices of the ``register("<platform>", …)`` block."""
    target = f'"{platform}",'
    for i, ln in enumerate(lines):
        if ln.strip() == "register(" and i + 1 < len(lines) and lines[i + 1].strip() == target:
            for j in range(i + 1, len(lines)):
                if lines[j].rstrip() == "    )":
                    return i, j
            raise UsageError(f"canary-flip: unterminated register() block for {platform!r}")
    raise UsageError(f'canary-flip: no register("{platform}", ...) block found')


def _remove_dict_entry(text: str, key: str) -> str:
    """Remove a ``"<key>": …`` entry from a dict literal, handling multi-line
    parenthesized string values (whose bodies may contain their own parens)."""
    lines = text.splitlines()
    needle = f'"{key}":'
    start = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith(needle)), None)
    if start is None:
        return text  # idempotent: nothing to remove
    end = start
    if lines[start].rstrip().endswith("("):
        for j in range(start + 1, len(lines)):
            if lines[j].strip() == "),":
                end = j
                break
        else:
            raise UsageError(f"canary-flip: unterminated _R entry for {key!r}")
    del lines[start : end + 1]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def plan_flip(
    init_source: str,
    rationales_source: str,
    platform: str,
    *,
    date: str = "",
) -> FlipEdits:
    """Compute the flipped ``__init__.py`` + ``_nofollow_rationales.py`` sources.

    Raises ``UsageError`` if the platform has no register block or its block is
    not ``dofollow="uncertain"``. The rationales output is ``ast.parse``-checked
    here (it is a full module); the init output is validated by the caller
    (``main``) against the real full file.
    """
    lines = init_source.splitlines()
    i, j = _find_register_block(lines, platform)

    new_block: list[str] = []
    saw_uncertain = False
    for k in range(i, j + 1):
        stripped = lines[k].strip()
        if stripped.startswith('dofollow="uncertain"'):
            saw_uncertain = True
            stamp = f" {date}" if date else ""
            new_block.append(f"        dofollow=True,  # OUR canary{stamp}: dofollow confirmed")
        elif stripped.startswith("rationale=") or stripped.startswith("referral_value="):
            continue  # drop — no longer required once dofollow=True
        else:
            new_block.append(lines[k])
    if not saw_uncertain:
        raise UsageError(
            f'canary-flip: {platform!r} register() block is not dofollow="uncertain" '
            "(already flipped or a different status)"
        )

    new_lines = lines[:i] + new_block + lines[j + 1 :]
    new_init = "\n".join(new_lines) + ("\n" if init_source.endswith("\n") else "")

    new_rationales = _remove_dict_entry(rationales_source, platform)
    ast.parse(new_rationales)  # full module — fail loudly if the removal broke it
    return FlipEdits(new_init=new_init, new_rationales=new_rationales)


def flip_tracker_row(text: str, platform: str, *, new_status: str = "flipped") -> str:
    """Set the status cell of ``platform``'s canary-pending.md row to ``new_status``."""
    out: list[str] = []
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) >= 6 and cells[1] == platform:
            parts = ln.split("|")
            parts[-2] = f" {new_status} "
            out.append("|".join(parts))
        else:
            out.append(ln)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def render_patch(path: str, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def _last_json(raw: str) -> dict[str, Any]:
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise UsageError("canary-flip: empty receipt (expected canary-seed JSONL)")
    try:
        return cast("dict[str, Any]", json.loads(lines[-1]))
    except json.JSONDecodeError as exc:
        raise UsageError(f"canary-flip: receipt is not valid JSON: {exc}") from exc


def _run(args: argparse.Namespace) -> None:
    raw = sys.stdin.read() if args.stdin else Path(args.from_receipt).read_text(encoding="utf-8")
    receipt = _last_json(raw)
    if receipt.get("platform") != args.platform:
        raise UsageError(
            f"canary-flip: receipt platform {receipt.get('platform')!r} != {args.platform!r}"
        )
    if receipt.get("verdict") != "dofollow":
        raise UsageError(
            f"canary-flip: refuse — verdict is {receipt.get('verdict')!r}, not 'dofollow'. "
            "Re-run canary-seed until it confirms dofollow before flipping."
        )

    import backlink_publisher.publishing.adapters as adapters_pkg  # noqa: F401  (populate registry)
    from backlink_publisher.publishing.registry import dofollow_status

    if dofollow_status(args.platform) != "uncertain":
        raise UsageError(
            f"canary-flip: {args.platform!r} is not currently dofollow=\"uncertain\" in the registry"
        )

    pkg_dir = Path(adapters_pkg.__file__).parent
    init_path = pkg_dir / "__init__.py"
    rat_path = pkg_dir / "_nofollow_rationales.py"
    tracker_path = pkg_dir.parents[3] / "docs" / "discovery" / "canary-pending.md"

    init_src = init_path.read_text(encoding="utf-8")
    rat_src = rat_path.read_text(encoding="utf-8")
    edits = plan_flip(init_src, rat_src, args.platform, date=args.date)
    ast.parse(edits.new_init)  # validate the real full file after the flip

    tracker_src = tracker_path.read_text(encoding="utf-8") if tracker_path.is_file() else None
    new_tracker = flip_tracker_row(tracker_src, args.platform) if tracker_src else None

    diffs = [
        render_patch("src/backlink_publisher/publishing/adapters/__init__.py", init_src, edits.new_init),
        render_patch(
            "src/backlink_publisher/publishing/adapters/_nofollow_rationales.py",
            rat_src,
            edits.new_rationales,
        ),
    ]
    if tracker_src is not None and new_tracker is not None and new_tracker != tracker_src:
        diffs.append(render_patch("docs/discovery/canary-pending.md", tracker_src, new_tracker))
    combined = "".join(diffs)

    if args.apply:
        init_path.write_text(edits.new_init, encoding="utf-8")
        rat_path.write_text(edits.new_rationales, encoding="utf-8")
        if new_tracker is not None:
            tracker_path.write_text(new_tracker, encoding="utf-8")
        print(combined, file=sys.stderr)
        print(
            f"applied: {args.platform} flipped to dofollow=True in the working tree "
            "(NOT committed — review with `git diff`, add a regression test, then commit).",
            file=sys.stderr,
        )
    else:
        patch_file = Path.cwd() / f"canary-flip-{args.platform}.patch"
        patch_file.write_text(combined, encoding="utf-8")
        print(combined)
        print(
            f"wrote {patch_file.name}; review it, then `git apply {patch_file.name}` "
            "(or re-run with --apply). Remember to add a regression test asserting "
            f"dofollow_status({args.platform!r}) is True.",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="canary-flip",
        description="Promote a dofollow='uncertain' adapter to dofollow=True from a canary verdict.",
    )
    parser.add_argument("platform", help="the uncertain platform to flip")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-receipt", help="path to a canary-seed JSONL verdict receipt")
    source.add_argument("--stdin", action="store_true", help="read the verdict receipt from stdin")
    parser.add_argument("--apply", action="store_true", help="edit the working tree (never commits)")
    parser.add_argument("--date", default="", help="stamp for the inline confirmation comment")
    args = parser.parse_args(argv)

    try:
        _run(args)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
