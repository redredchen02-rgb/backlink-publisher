"""``verify-dofollow <slug>`` — probe a published platform's live anchor.

Reads the latest published URL from ``verify-queue.jsonl`` (keyed by slug),
fetches the live page, inspects the target anchor, and writes the
``dofollow`` verdict back to the operator's catalog override YAML.

Exit codes:
  0  — advisory: verdict printed (page unreachable is still exit 0)
  2  — usage error (missing slug, bad args)
  5  — I/O error reading/writing queue or catalog file
"""

from __future__ import annotations

from argparse import ArgumentParser
import json
from pathlib import Path
import sys

import yaml

from backlink_publisher._util.errors import emit_envelope_and_exit
from backlink_publisher.config.loader import _config_dir
from backlink_publisher.persistence.safe_write import atomic_write
from backlink_publisher.publishing.adapters.link_attr_verifier import (
    verify_link_attributes,
)

_QUEUE_FILENAME = "verify-queue.jsonl"


def _resolve_queue_path(config_dir: Path) -> Path:
    return config_dir / _QUEUE_FILENAME


def _find_latest_for_slug(
    queue_path: Path, slug: str
) -> str | None:
    """Return the latest ``published_url`` for *slug* from the queue JSONL.

    Returns ``None`` when the queue file is missing, empty, or contains
    no entry for *slug*.
    """
    if not queue_path.exists():
        return None

    latest_url: str | None = None
    latest_ts: str = ""
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("slug") == slug:
                ts = row.get("ts_utc", "")
                if ts >= latest_ts:
                    latest_ts = ts
                    latest_url = row.get("published_url")
    return latest_url


def _find_catalog_path(slug: str, config_dir: Path) -> Path | None:
    """Return path to the catalog YAML that owns *slug*.

    Precedence: user override dir → built-in dir.  Returns ``None`` when
    *slug* is not a catalog-driven platform.
    """
    # User override dir first.
    user_dir = config_dir / "catalog"
    user_path = user_dir / f"{slug}.yaml"
    if user_path.exists():
        return user_path
    user_path_yml = user_dir / f"{slug}.yml"
    if user_path_yml.exists():
        return user_path_yml

    # Built-in dir.
    built_in_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "publishing" / "adapters" / "catalog"
    )
    built_path = built_in_dir / f"{slug}.yaml"
    if built_path.exists():
        return built_path
    built_path_yml = built_in_dir / f"{slug}.yml"
    if built_path_yml.exists():
        return built_path_yml

    return None


def _write_dofollow_to_catalog(
    catalog_path: Path, slug: str, dofollow: bool,
) -> None:
    """Atomically write the ``dofollow`` verdict to the user override catalog.

    Always writes to ``<config_dir>/catalog/<slug>.yaml`` — never mutates a
    built-in (tracked) YAML file in-place.  The catalog overlay machinery
    in ``register_catalog_entries`` already gives user dir precedence.
    """
    config_dir = _config_dir()
    user_dir = config_dir / "catalog"
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / catalog_path.name

    try:
        raw = catalog_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        emit_envelope_and_exit(
            "CatalogParseError", 5,
            f"{catalog_path}: YAML parse error: {e}",
        )
    if not isinstance(data, dict):
        emit_envelope_and_exit(
            "CatalogParseError", 5,
            f"{catalog_path}: expected top-level mapping",
        )

    if slug not in data or not isinstance(data[slug], dict):
        emit_envelope_and_exit(
            "CatalogParseError", 5,
            f"{catalog_path}[{slug!r}]: entry not found or not a mapping",
        )

    data[slug]["dofollow"] = dofollow
    new_raw = yaml.dump(data, default_flow_style=False, allow_unicode=True)

    # Preserve the original YAML's top-level comment block (txtfyi.yaml has
    # a docstring-style comment above the slug key).  The simplest way is to
    # keep the original file's leading comment lines.
    original_lines = raw.splitlines(keepends=True)
    comment_lines: list[str] = []
    for line in original_lines:
        if line.startswith("#") or line.strip() == "":
            comment_lines.append(line)
        else:
            break

    if comment_lines:
        new_raw = "".join(comment_lines) + "\n" + new_raw

    atomic_write(target, new_raw, mode=0o644)


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="verify-dofollow",
        description=(
            "Probe a published platform's live page, verify the target "
            "backlink anchor, and update the catalog dofollow field."
        ),
    )
    parser.add_argument(
        "slug",
        help="Platform slug (e.g. txtfyi)",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Override config directory (default: auto-detected)",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    config_dir = Path(args.config_dir) if args.config_dir else _config_dir()

    # 1. Read queue → find latest URL for slug.
    queue_path = _resolve_queue_path(config_dir)
    published_url = _find_latest_for_slug(queue_path, args.slug)

    if published_url is None:
        print(
            f"verify-dofollow: no queue entry for {args.slug!r} "
            f"(queue: {queue_path})",
            file=sys.stderr,
        )
        return

    # 2. Verify link attributes on the live page.
    print(f"verifying {published_url} …", file=sys.stderr)
    result = verify_link_attributes(published_url)

    if result.get("verification") == "skipped":
        print(
            f"verify-dofollow: verification skipped — {result.get('reason', 'unknown')}",
            file=sys.stderr,
        )
        return

    # 3. Determine verdict.
    target_nofollow = result.get("target_nofollow", False)
    nofollow_detected = result.get("nofollow_detected", False)
    is_dofollow = not (target_nofollow or nofollow_detected)

    print(f"  total_anchors: {result.get('total_anchors', '?')}")
    print(f"  nofollow_anchors: {result.get('nofollow_anchors', '?')}")
    print(f"  target_nofollow: {target_nofollow}")
    print(f"  dofollow: {is_dofollow}")

    # 4. Write back dofollow verdict to catalog YAML.
    catalog_path = _find_catalog_path(args.slug, config_dir)
    if catalog_path is None:
        print(
            f"verify-dofollow: {args.slug!r} is not a catalog-driven platform — "
            f"no YAML to update",
            file=sys.stderr,
        )
        return

    _write_dofollow_to_catalog(catalog_path, args.slug, is_dofollow)
    print(f"  wrote dofollow={is_dofollow} to catalog YAML", file=sys.stderr)


if __name__ == "__main__":
    main()
