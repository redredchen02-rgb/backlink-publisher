"""OnboardingSqliteStore — persists the single 'dismissed' flag (Plan 2026-07-09-001).

Single-row blob store in ``webui.db`` table ``onboarding_meta``. Only one bit of
operator UI state is persisted for the onboarding wizard: whether the operator
has asked to stop seeing the first-run guide. Every per-step completion status is
DERIVED from real system state at read time (channels bound, LLM configured,
keyword pools, campaigns, published history) — see ``webui_app.api.onboarding_api``
— so this store holds no driftable checklist and can never disagree with reality.
"""

from __future__ import annotations

from .sqlite_base import BlobSqliteStore


class OnboardingSqliteStore(BlobSqliteStore):
    """Single-row blob store for onboarding UI state.

    Table: ``onboarding_meta (id INTEGER PRIMARY KEY, data_json TEXT NOT NULL)``.
    ``load()`` returns ``{}`` when empty; the only key we use is ``dismissed`` (bool).
    """

    _table_name = "onboarding_meta"
    _value_type = dict

    def is_dismissed(self) -> bool:
        data = self.load()
        return bool(data.get("dismissed", False)) if isinstance(data, dict) else False

    def set_dismissed(self, value: bool) -> None:
        self.save({"dismissed": bool(value)})
