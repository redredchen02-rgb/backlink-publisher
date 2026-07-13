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
from .error_reports import error_report_store
from .history import HistoryStore
from .onboarding import OnboardingSqliteStore
from .operation_store import OperationSqliteStore
from .profiles import ProfilesSqliteStore
from .publish_defaults import PublishDefaultsSqliteStore
from .queue_store import QueueSqliteStore
from .schedule import ScheduleSqliteStore
from .sqlite_base import WebUIDatabase
from .verify_health import verify_health_store


def _store_path(filename: str) -> Path:
    """Resolve a store file path under the current config dir."""
    return _resolve_config_dir() / filename


# Shared WebUIDatabase instance for all stores using webui.db.
# Lazily resolved so test fixtures that mutate BACKLINK_PUBLISHER_CONFIG_DIR
# before first access get the correct path. Invalidated by _refresh_paths().
_WEBUI_DB: WebUIDatabase | None = None


def _get_webui_db() -> WebUIDatabase:
    global _WEBUI_DB
    if _WEBUI_DB is None:
        _WEBUI_DB = WebUIDatabase(_resolve_config_dir() / "webui.db")
    return _WEBUI_DB


def _make_schedule_store() -> ScheduleSqliteStore:
    config_dir = _resolve_config_dir()
    store = ScheduleSqliteStore(_get_webui_db())
    store.migrate_from_json(config_dir)
    return store


def _make_profiles_store() -> ProfilesSqliteStore:
    config_dir = _resolve_config_dir()
    store = ProfilesSqliteStore(_get_webui_db())
    store.migrate_from_json(config_dir)
    return store


def _make_queue_store() -> QueueSqliteStore:
    config_dir = _resolve_config_dir()
    store = QueueSqliteStore(_get_webui_db())
    store.migrate_from_json(config_dir)
    return store


def _make_drafts_store() -> DraftsSqliteStore:
    config_dir = _resolve_config_dir()
    store = DraftsSqliteStore(_get_webui_db())
    store.migrate_from_json(config_dir)
    return store


def _make_campaign_store() -> CampaignSqliteStore:
    config_dir = _resolve_config_dir()
    store = CampaignSqliteStore(_get_webui_db())
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
    return PublishDefaultsSqliteStore(_get_webui_db())


def _make_batch_ops_store() -> BatchOpsSqliteStore:
    return BatchOpsSqliteStore(_get_webui_db())


def _make_operation_store() -> OperationSqliteStore:
    return OperationSqliteStore(_get_webui_db())


publish_defaults_store = _LazyStore(_make_publish_defaults_store)
batch_ops_store = _LazyStore(_make_batch_ops_store)
operation_store = _LazyStore(_make_operation_store)


def _make_onboarding_store() -> OnboardingSqliteStore:
    return OnboardingSqliteStore(_get_webui_db())


onboarding_store = _LazyStore(_make_onboarding_store)


def _refresh_paths() -> None:
    """Rebind every lazy store so the next access resolves a fresh path.

    Test fixtures that mutate ``BACKLINK_PUBLISHER_CONFIG_DIR``
    mid-session (e.g. ``test_config_dir_falls_back_when_env_var_unset``)
    must call this to discard previously-cached store instances and
    have them re-resolve from the updated env var.
    """
    global _WEBUI_DB
    WebUIDatabase.close_all()
    _WEBUI_DB = None
    for store in (history_store, profiles_store, drafts_store,
                  schedule_store, queue_store, channel_status_store,
                  campaign_store, publish_defaults_store, batch_ops_store,
                  operation_store, onboarding_store, verify_health_store,
                  error_report_store):
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
    "verify_health_store",
    "error_report_store",
    "operation_store",
    "OnboardingSqliteStore",
    "onboarding_store",
    "_refresh_paths",
]
