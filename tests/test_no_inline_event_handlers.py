"""Permanent guard: legacy Jinja templates must not use inline on* handlers.

Audit finding [41]: the enforced anti-rot rule (CLAUDE.md: "No inline on* handlers —
use data-action + delegated addEventListener") was violated on live pages —
_tab_new.html's publish-chain button and batch_campaign.html's mode tabs. The only
existing structure test rendered index.html WITHOUT `config`, so the offending button
(inside `{% if config %}`) was never emitted and escaped detection.

This guard scans the template SOURCE (not rendered output), so handlers are caught
regardless of the Jinja conditions guarding them. The resource-load `onload=`/`onerror=`
idioms (e.g. the async-CSS font-preload swap) are deliberate performance patterns, not
user-interaction app logic, and are intentionally not matched.
"""

from __future__ import annotations

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parent.parent / "webui_app" / "templates"

# User-interaction event handlers only (deliberately excludes load/error, which are
# resource-loading idioms rather than app event logic).
_HANDLER_RE = re.compile(
    r"\son(click|change|submit|input|keyup|keydown|focus|blur|mouseover|mouseout)=",
    re.IGNORECASE,
)


def test_no_inline_event_handlers_in_templates() -> None:
    offenders: list[str] = []
    for html in sorted(_TEMPLATES.rglob("*.html")):
        for i, line in enumerate(html.read_text(encoding="utf-8").splitlines(), 1):
            if _HANDLER_RE.search(line):
                offenders.append(f"{html.relative_to(_TEMPLATES)}:{i}: {line.strip()}")
    assert not offenders, (
        "Inline on* handlers violate the enforced anti-rot rule (use data-action + "
        "delegated addEventListener):\n" + "\n".join(offenders)
    )
