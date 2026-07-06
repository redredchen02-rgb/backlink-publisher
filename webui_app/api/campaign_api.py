"""CampaignAPI — batch-campaign creation facade.

Phase-A-style facade (Plan 2026-06-18-002 U7, batch_campaign page). Centralises
the campaign-creation form bootstrap (registered platforms + connection-state
partition) and the submit path (validate → ``campaign_store.create`` → hand to
the CampaignWorker) so the ``/api/v1/campaigns`` HTTP binding stays thin.

REUSES the existing ``campaign_store`` + ``partition_channels_by_connection``
(the same decision point the settings overview and legacy picker use), so the
platform-selectability rules stay single-source.

Scope: the creation form only. The campaign PROGRESS view (``/campaign/<id>``)
is a separate route, not migrated here — the SPA navigates out to it on success.
"""

from __future__ import annotations

import json
from typing import Any

_MAX_SEEDS = 10


class CampaignAPI:
    """Encapsulates batch-campaign creation (bootstrap + validate + create)."""

    # ── read: form bootstrap ──────────────────────────────────────────────

    def form_bootstrap(self) -> dict[str, Any]:
        """Platforms + connection-state partition for the creation form picker."""
        from backlink_publisher.publishing.registry import registered_platforms
        return {
            "platforms": sorted(registered_platforms()),
            "publish_partition": self._build_publish_partition(),
        }

    @staticmethod
    def _build_publish_partition() -> dict[str, Any] | None:
        """Partition publishable platforms by connection state. None on failure.

        Mirrors the legacy route's helper: fail-soft so the SPA falls back to the
        flat ``platforms`` list and the form never breaks on a status-store error.
        """
        try:
            from backlink_publisher.config import load_config
            from backlink_publisher.publishing.registry import active_platforms
            from webui_store import channel_status

            from ..binding_status import get_channel_status
            from ..helpers.channel_tiers import (
                merge_verify_health,
                partition_channels_by_connection,
            )

            cfg = load_config()
            dashboard_channels = [
                (name, get_channel_status(name, cfg)) for name in active_platforms()
            ]
            try:
                statuses = channel_status.list_all()
            except Exception:
                # debt: campaign-bootstrap-status-fail-soft
                statuses = {}
            try:
                from webui_store import verify_health
                statuses = merge_verify_health(statuses, verify_health.expired_channels())
            except Exception:
                # debt: campaign-bootstrap-status-fail-soft
                pass
            return partition_channels_by_connection(dashboard_channels, statuses)
        except Exception:
            # debt: campaign-bootstrap-status-fail-soft
            return None

    # ── write: validate + create ──────────────────────────────────────────

    def create(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate the form and create a campaign.

        Returns ``{"ok": False, "errors": {field: msg}}`` (caller → 422) or
        ``{"ok": True, "campaign_id": id}`` (caller → 200; SPA then navigates to
        the legacy ``/campaign/<id>`` progress page).
        """
        parsed_seeds, errors = self._validate(raw)
        if errors:
            return {"ok": False, "errors": errors}

        from webui_store import campaign_store

        platforms = self._valid_platforms(raw)
        mode = (raw.get("mode") or "draft").strip()
        cap = self._parse_cap(raw.get("cap"))[0]
        seed_delay = self._parse_delay(raw.get("seed_delay"))[0]

        campaign_id = campaign_store.create(
            mode=mode, platforms=platforms, seeds=parsed_seeds, cap=cap,
        )

        # Hand to the worker when one is running (best-effort; creation still
        # succeeds if no worker is configured — mirrors the legacy route).
        try:
            from flask import current_app
            worker = current_app.config.get("CAMPAIGN_WORKER")
            if worker is not None:
                worker.start_campaign(campaign_id, {
                    "platforms": platforms, "mode": mode, "cap": cap, "seed_delay": seed_delay,
                })
        except Exception:
            # debt: campaign-worker-dispatch-best-effort
            pass

        return {"ok": True, "campaign_id": campaign_id}

    # ── validation helpers ────────────────────────────────────────────────

    def _validate(self, raw: dict[str, Any]) -> tuple[list[dict], dict[str, str]]:
        """Validate every field. Returns (parsed_seeds, errors)."""
        errors: dict[str, str] = {}
        parsed_seeds = self._parse_seeds(raw.get("seeds", ""), errors)

        if not self._valid_platforms(raw):
            errors["platforms"] = "至少选择一个平台"

        if (raw.get("mode") or "draft").strip() not in ("draft", "publish"):
            errors["mode"] = "模式必须选择 draft 或 publish"

        _, cap_err = self._parse_cap(raw.get("cap"))
        if cap_err:
            errors["cap"] = cap_err

        _, delay_err = self._parse_delay(raw.get("seed_delay"))
        if delay_err:
            errors["seed_delay"] = delay_err

        return parsed_seeds, errors

    @staticmethod
    def _parse_seeds(seed_text: str, errors: dict[str, str]) -> list[dict]:
        """Parse the seeds textarea (≤10 JSON lines, each needs ``seed_text``)."""
        lines = [line.strip() for line in str(seed_text or "").split("\n") if line.strip()]
        if not lines:
            errors["seeds"] = "至少输入一条 seed（每行一条 JSON）"
            return []
        if len(lines) > _MAX_SEEDS:
            errors["seeds"] = f"最多 {_MAX_SEEDS} 条 seed，当前 {len(lines)} 条"
            return []

        parsed: list[dict] = []
        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("not a JSON object")
                if "seed_text" not in obj:
                    raise ValueError("missing seed_text field")
                parsed.append(obj)
            except (json.JSONDecodeError, ValueError) as exc:
                detail = f"第 {i + 1} 行解析失败: {exc}"
                errors["seeds"] = f"{errors['seeds']}; {detail}" if errors.get("seeds") else detail
        return parsed

    @staticmethod
    def _valid_platforms(raw: dict[str, Any]) -> list[str]:
        from backlink_publisher.publishing.registry import registered_platforms
        allowed = set(registered_platforms())
        selected = raw.get("platforms") or []
        if not isinstance(selected, list):
            selected = [selected]
        return [p for p in selected if p in allowed]

    @staticmethod
    def _parse_cap(cap_raw: Any) -> tuple[int | None, str | None]:
        cap_str = str(cap_raw or "").strip()
        if not cap_str:
            return None, None
        try:
            cap = int(cap_str)
        except (ValueError, TypeError):
            return None, "上限必须是正整数"
        return (cap, None) if cap >= 1 else (None, "上限必须 >= 1")

    @staticmethod
    def _parse_delay(delay_raw: Any) -> tuple[int, str | None]:
        delay_str = str(delay_raw if delay_raw is not None else "0").strip()
        if not delay_str:
            return 0, None
        try:
            return max(0, int(delay_str)), None
        except (ValueError, TypeError):
            return 0, "延迟必须是整数（秒）"
