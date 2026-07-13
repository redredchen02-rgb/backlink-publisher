"""Argparse declaration for the plan-backlinks CLI shell.

Extracted from :mod:`.core` (D1 complexity refactor, 2026-07-13) so the shell
stays within its monolith SLOC ceiling. Pure declaration — no I/O, no side
effects beyond touching the adapter registry for the ``--default-platform``
choices.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backlink_publisher.publishing.registry import registered_platforms

if TYPE_CHECKING:
    import argparse

def _build_parser() -> argparse.ArgumentParser:
    """Build the plan-backlinks argparse parser (pure declaration, no I/O)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="plan-backlinks",
        description="Generate backlink article payloads from seed URLs.",
    )
    parser.add_argument(
        "--input", "-i",
        type=argparse.FileType("r"),
        default=None,
        help="Input JSONL file (default: stdin)",
    )
    parser.add_argument(
        "--from-csv",
        default=None,
        metavar="FILE",
        help="Read target URLs from a CSV/text file (one URL per line). Use '-' for stdin.",
    )
    parser.add_argument(
        "--from-sitemap",
        default=None,
        metavar="URL",
        help="Fetch target URLs from a sitemap XML URL.",
    )
    parser.add_argument(
        "--default-platform",
        default="blogger",
        choices=registered_platforms(),
        help="Platform for --from-csv / --from-sitemap rows (default: blogger)",
    )
    parser.add_argument(
        "--default-language",
        default="zh-CN",
        choices=["zh-CN", "en", "ru", "ko"],
        help="Language for --from-csv / --from-sitemap rows (default: zh-CN)",
    )
    parser.add_argument(
        "--default-url-mode",
        default="A",
        choices=["A", "B", "C"],
        help="URL mode for --from-csv / --from-sitemap rows (default: A)",
    )
    parser.add_argument(
        "--default-publish-mode",
        default="draft",
        choices=["draft", "publish"],
        help="Publish mode for --from-csv / --from-sitemap rows (default: draft)",
    )
    parser.add_argument(
        "--work-count",
        type=int,
        default=10,
        metavar="N",
        help=(
            "Per-row article count for the work-themed dispatcher path "
            "(default: 10). Ignored for legacy zh-short / long-form rows."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="WARN",
        choices=["DEBUG", "INFO", "WARN", "ERROR"],
        help="Log verbosity (default: WARN)",
    )
    parser.add_argument(
        "--no-fetch-verify",
        action="store_true",
        default=False,
        help=(
            "Skip the plan-time URL content gate (default: enabled). Each row's "
            "URLs are normally fetched via content_fetch.verify_url_has_content "
            "and required to return HTTP 200 with a non-empty <title> or "
            "og:title before being added to the article. Use this flag in "
            "dev / replay / staging when target sites are intentionally offline. "
            "Plan ref: docs/plans/2026-05-14-007-feat-url-content-fetch-gate-plan.md"
        ),
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        default=False,
        help="Enable cProfile profiling (saved to ~/.cache/backlink-publisher/profiles/)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        dest="max_rows",
        help="Maximum seed rows to process; excess rows are truncated with a warning (default: 1000)",
    )
    return parser
