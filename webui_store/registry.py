"""WebUIStores — Flask app-context store registry (Plan 2026-05-22 P7 C1).

Replaces ad-hoc module-level singleton imports in WebUI code with a
proper Flask extension pattern::

    from flask import current_app

    stores = current_app.extensions['webui_stores']
    history = stores.history.load()

Each property **delegates to the module-level ``_LazyStore`` singleton** in
``webui_store/__init__.py`` rather than constructing a fresh store instance.
This is load-bearing for the SQLite migration (Plan 2026-06-03-008 Unit 8):
all six operational stores now share a single ``webui.db``. If ``WebUIStores``
built its own instances, each store would hold an independent
``threading.RLock`` pointing at the same db file — the per-store in-process
lock invariant would be broken and concurrent writes would only be serialised
by SQLite's ``busy_timeout``, not by Python locks. Delegating to the singleton
keeps exactly one lock per store across both access paths.
"""

from __future__ import annotations

from flask import Flask

from . import (
    campaign_store,
    channel_status_store,
    drafts_store,
    history_store,
    profiles_store,
    queue_store,
    schedule_store,
)
from .base import Store


class WebUIStores:
    """Flask-extension view over the module-level store singletons.

    Holds no store state of its own — every property returns the shared
    ``_LazyStore`` singleton so there is exactly one backing instance (and
    one lock) per store process-wide.
    """

    def __init__(self) -> None:
        self._app: Flask | None = None

    def init_app(self, app: Flask) -> None:
        self._app = app
        app.extensions['webui_stores'] = self

    # ── Store properties — all delegate to module-level singletons ────────

    @property
    def history(self) -> Store:
        return history_store

    @property
    def profiles(self) -> Store:
        return profiles_store

    @property
    def drafts(self) -> Store:
        return drafts_store

    @property
    def schedule(self) -> Store:
        return schedule_store

    @property
    def queue(self) -> Store:
        return queue_store

    @property
    def campaign(self) -> Store:
        return campaign_store

    @property
    def channel_status(self) -> Store:
        return channel_status_store
