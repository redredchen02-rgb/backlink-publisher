"""Single source of truth for the keep-alive sticky-platform set.

Lives in core (not ``webui_app``) so ``keepalive/chain.py`` can read it without a
reverse import into the WebUI. ``webui_app/services/_keepalive_engine.py``
re-imports it to preserve its ``RUNTIME_STICKY_PLATFORMS`` / ``_RUNTIME_STICKY``
public aliases — the import, not duplication, enforces the "no S2↔S3 drift"
invariant.
"""
from __future__ import annotations

RUNTIME_STICKY_PLATFORMS = ("blogger",)
