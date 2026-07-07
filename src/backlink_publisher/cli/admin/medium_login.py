"""`medium-login` CLI — Plan 2026-05-19-005 Unit 1.

Transparent alias for ``bind-channel --channel medium``.

Plan 2026-05-19-005 (Medium adapter收敛 velog 模式) wants a CLI entry
parallel to ``velog-login`` so operators bind both channels through
the same surface. The alias mirrors ``velog_login`` exactly:

  - prints a one-line informational banner to **stderr**
    (``medium-login is an alias for: bind-channel --channel medium``)
  - prepends ``["--channel", "medium"]`` to the operator's argv
  - delegates to ``bind_channel.main``

Operator cannot pass ``--channel`` explicitly via this alias — the
channel is implied by the entry point name. Passing ``--channel`` is
rejected with ``UsageError`` (exit_code=1).

Beyond the alias itself, Plan 005 Unit 1 also extends the medium
binding flow to write ``medium-cookies.json`` + ``medium-meta.json``
(cookies-only credential format + UA fingerprint for the future
``MediumGraphQLAdapter``). That extension lives in the medium recipe
``post_persist`` hook, not in this alias.
"""

from __future__ import annotations

from collections.abc import Sequence
import sys
from typing import Any

from backlink_publisher._util.errors import handle_error, UsageError
from backlink_publisher.cli.admin import bind_channel

_BANNER = "medium-login is an alias for: bind-channel --channel medium"


def main(argv: Sequence[str] | None = None, *, _browser_runner: Any = None) -> None:
    """Entry point for the ``medium-login`` console script.

    Always prints the alias banner to stderr first so plan-005 readers
    invoking this entry point see the redirect.
    """
    print(_BANNER, file=sys.stderr, flush=True)

    passthrough = list(sys.argv[1:] if argv is None else argv)

    # Reject any explicit --channel — the alias implies it. Detection is
    # exact: argparse-style long option only (operators don't have a short
    # form to abuse here).
    if "--channel" in passthrough:
        try:
            raise UsageError(
                "medium-login: explicit --channel is not allowed; the alias "
                "already implies --channel medium. Use bind-channel directly "
                "if you need a different channel."
            )
        except UsageError as exc:
            handle_error(exc)
            return  # unreachable

    bind_channel.main(
        ["--channel", "medium", *passthrough],
        _browser_runner=_browser_runner,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
