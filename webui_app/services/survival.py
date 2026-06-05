"""Survival-rate dashboard view (R5).

Thin presentation layer over ``events.survival_query.compute_survival``: adds a
zh-CN headline + sub-label per state so loading/empty/insufficient/maturing/
stale read visually distinct (not one gray panel), and keeps everything
JSON-serializable. ``store``/``now`` are injectable for tests.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Per-state zh-CN copy. Kept here (presentation) so survival_query stays a pure
# data layer. Headline + sub must always differ across states (Deferred design
# note: loading vs empty vs insufficient vs stale are not one panel).
_COPY = {
    "ok": ("存活率", "已成熟链接中仍 live + dofollow 的占比"),
    "insufficient": ("样本不足", "已成熟链接太少，暂不计算百分比（继续累积中）"),
    "maturing": ("成熟中", "链接尚未满 {days} 天，存活率需等待样本成熟"),
    "empty": ("暂无数据", "还没有已成熟的链接可统计"),
    "unavailable": ("暂时不可用", "读取存活数据时出错，请稍后再试"),
}


def build_survival_view(*, store=None, now: datetime | None = None) -> dict[str, Any]:
    """Return the survival dashboard payload for the screen bootstrap.

    Never raises: a query failure degrades to an honest ``unavailable`` state so
    the route can render without 500ing.
    """
    try:
        from backlink_publisher.events.survival_query import compute_survival

        data = compute_survival(store=store, now=now)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("survival view: compute failed: %s", exc)
        data = {
            "state": "unavailable",
            "survival_rate": None,
            "survival_pct": None,
            "sample_size": 0,
            "survived": 0,
            "mature_count": 0,
            "maturing_count": 0,
            "stale_count": 0,
            "stale": False,
            "stale_days": None,
            "partial": False,
            "cohort_days": 30,
        }

    state = data.get("state", "unavailable")
    headline, sub = _COPY.get(state, _COPY["unavailable"])
    days = data.get("cohort_days", 30)

    view = dict(data)
    view["headline"] = headline
    view["sub"] = sub.format(days=days)
    # Display string for the rate (percentage or an em-dash placeholder).
    view["display"] = (
        f"{data['survival_pct']}%" if data.get("survival_pct") is not None else "—"
    )
    # A single boolean the template uses to decide whether to show the big number.
    view["has_rate"] = data.get("survival_rate") is not None
    return view
