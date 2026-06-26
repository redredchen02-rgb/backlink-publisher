"""WebUI state persistence — Plan 2026-05-18-001 Unit 2.

Eight ``_LazyStore`` wrappers replace the eager module-level singletons:
``history_store``, ``profiles_store``, ``drafts_store``, ``schedule_store``,
``queue_store``, ``campaign_store``, ``publish_defaults_store``,
``batch_ops_store``. Each store resolves its backing-file path from
``_config_dir()`` on first access rather than at import time.

Plan 2026-05-22 P7 C1: ``_refresh_paths()`` is now a no-op (stores are
lazy) and is retained only for backward compatibility. New code should
access stores through ``current_app.extensions['webui_stores']`` (see
``registry.py``) or just import the module-level names below — they
work identically.
"""

from __future__ import annotations

from pathlib import Path

from backlink_publisher.config.loader import _resolve_config_dir

from .base import _LazyStore, JsonStore, Store
from .batch_ops import BatchOpsSqliteStore
from .campaign_store import CampaignSqliteStore, CampaignStore
from .channel_status import channel_status_store
from .drafts import DraftsSqliteStore, DraftsStore
from .history import HistoryStore
from .profiles import ProfilesSqliteStore
from .publish_defaults import PublishDefaultsSqliteStore
from .queue_store import QueueSqliteStore
from .schedule import ScheduleSqliteStore
from .sqlite_base import WebUIDatabase


def _store_path(filename: str) -> Path:
    """Resolve a store file path under the current config dir."""
    return _resolve_config_dir() / filename


def _make_schedule_store() -> ScheduleSqliteStore:
    config_dir = _resolve_config_dir()
    store = ScheduleSqliteStore(WebUIDatabase(config_dir / "webui.db"))
    store.migrate_from_json(config_dir)
    return store


def _make_profiles_store() -> ProfilesSqliteStore:
    config_dir = _resolve_config_dir()
    store = ProfilesSqliteStore(WebUIDatabase(config_dir / "webui.db"))
    store.migrate_from_json(config_dir)
    return store


def _make_queue_store() -> QueueSqliteStore:
    config_dir = _resolve_config_dir()
    store = QueueSqliteStore(WebUIDatabase(config_dir / "webui.db"))
    store.migrate_from_json(config_dir)
    return store


def _make_drafts_store() -> DraftsSqliteStore:
    config_dir = _resolve_config_dir()
    store = DraftsSqliteStore(WebUIDatabase(config_dir / "webui.db"))
    store.migrate_from_json(config_dir)
    return store


def _make_campaign_store() -> CampaignSqliteStore:
    config_dir = _resolve_config_dir()
    store = CampaignSqliteStore(WebUIDatabase(config_dir / "webui.db"))
    store.migrate_from_json(config_dir)
    return store


# Singleton bindings — lazily resolved on first access so test fixtures
# that set BACKLINK_PUBLISHER_CONFIG_DIR before accessing these don't
# need _refresh_paths().
history_store = _LazyStore(
    lambda: HistoryStore(_store_path("publish-history.json"))
)
profiles_store = _LazyStore(_make_profiles_store)
drafts_store = _LazyStore(_make_drafts_store)
schedule_store = _LazyStore(_make_schedule_store)
queue_store = _LazyStore(_make_queue_store)
campaign_store = _LazyStore(_make_campaign_store)


def _make_publish_defaults_store() -> PublishDefaultsSqliteStore:
    config_dir = _resolve_config_dir()
    return PublishDefaultsSqliteStore(WebUIDatabase(config_dir / "webui.db"))


def _make_batch_ops_store() -> BatchOpsSqliteStore:
    config_dir = _resolve_config_dir()
    return BatchOpsSqliteStore(WebUIDatabase(config_dir / "webui.db"))


publish_defaults_store = _LazyStore(_make_publish_defaults_store)
batch_ops_store = _LazyStore(_make_batch_ops_store)


def _refresh_paths() -> None:
    """Rebind every lazy store so the next access resolves a fresh path.

    Test fixtures that mutate ``BACKLINK_PUBLISHER_CONFIG_DIR``
    mid-session (e.g. ``test_config_dir_falls_back_when_env_var_unset``)
    must call this to discard previously-cached store instances and
    have them re-resolve from the updated env var.
    """
    for store in (history_store, profiles_store, drafts_store,
                  schedule_store, queue_store, channel_status_store,
                  campaign_store, publish_defaults_store, batch_ops_store):
        store.reset()


__all__ = [
    "Store",
    "JsonStore",
    "_LazyStore",
    "_store_path",
    "CampaignStore",
    "CampaignSqliteStore",
    "DraftsStore",
    "DraftsSqliteStore",
    "HistoryStore",
    "ProfilesSqliteStore",
    "QueueSqliteStore",
    "campaign_store",
    "history_store",
    "profiles_store",
    "drafts_store",
    "schedule_store",
    "queue_store",
    "channel_status_store",
    "BatchOpsSqliteStore",
    "batch_ops_store",
    "PublishDefaultsSqliteStore",
    "publish_defaults_store",
    "_refresh_paths",
]
