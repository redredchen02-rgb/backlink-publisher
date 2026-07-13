"""``bp-report-bug`` — self-contained diagnostic bundle generator.

See :mod:`backlink_publisher.cli.report_bug._build` for the assembly logic and
:mod:`backlink_publisher.cli.report_bug.main` for the CLI entrypoint.
"""

from __future__ import annotations

from .main import main

__all__ = ["main"]
