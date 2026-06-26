"""Survival-rate view builder (plan 008 R5).

Mirrors keep_alive.py: injectable ``store``/``now`` for tests; JSON-serializable
dict with no sets; degrade to unavailable/empty without raising.
"""

from __future__ import annotations

from datetime import datetime

from backlink_publisher.events.store import EventStore
from backlink_publisher.events.survival_query import compute_survival


def _display_fields(data: dict) -> dict:
    """Add presentation-layer fields to the raw compute_survival output."""
    state = data.get("state", "empty")
    rate = data.get("survival_rate")
    has_rate = state == "ok" and rate is not None
    display = f"{rate * 100:.1f}%" if has_rate else "—"
    if state == "ok":
        headline = f"{display} 链接仍存活"
        sub = f"样本量 {data.get('sample_size', 0)} 条（≥30天成熟外链）"
    elif state == "insufficient":
        headline = "样本量不足"
        sub = f"已审计 {data.get('sample_size', 0)} 条，需 ≥2 条才能计算存活率"
    else:
        headline = "暂无成熟外链"
        sub = "发布 30 天后的外链将纳入统计"
    return {**data, "has_rate": has_rate, "display": display,
            "headline": headline, "sub": sub}


def build_survival_view(*, store: EventStore | None = None, now: datetime | None = None) -> dict:
    """Return the survival-dashboard payload with display fields.

    Never raises — callers rely on this to render an honest unavailable state.
    """
    try:
        data = compute_survival(store, now=now)
        return _display_fields(data)
    except Exception:  # noqa: BLE001
        return {
            "state": "empty",
            "survival_rate": None,
            "sample_size": 0,
            "survived": 0,
            "mature_count": 0,
            "maturing_count": 0,
            "stale": False,
            "stale_count": 0,
            "partial": False,
            "stale_days": None,
            "has_rate": False,
            "display": "—",
            "headline": "暂无数据",
            "sub": "",
            "unavailable": True,
        }
