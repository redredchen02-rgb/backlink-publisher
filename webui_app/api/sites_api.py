"""SitesAPI — structured wrapper around the work-themed site configuration.

Phase-A-style facade (Plan 2026-06-18-002 U7, sites page). Centralises the
three-URL config lifecycle, the autopilot toggle, the per-site list (with live
APScheduler next-run lookup) and the two read-only side-panel widgets so the
``/api/v1/sites`` HTTP binding stays thin.

It REUSES the existing shared primitives — ``config.load_config/save_config``,
the ``_util.url`` validators, and the ``helpers.url_meta`` derivation helpers —
so the anchor-pool / work-URL derivation rules stay single-source. The legacy
``/sites`` Jinja route keeps its own copy until U8 retires it (the plan's
sanctioned migration-window dual-truth); both sit on the same helpers.

Every method returns a neutral result dict (``ok`` + payload / ``error_code``)
that callers translate to their own transport: the legacy route → render /
redirect / flash; ``/api/v1`` → JSON 200 or RFC 9457 problem+json.
"""

from __future__ import annotations

import sys
from typing import Any
from urllib.parse import quote as _quote

from backlink_publisher._util.errors import InputValidationError
from backlink_publisher._util.logger import plan_logger
from backlink_publisher._util.url import validate_https_url, validate_main_domain_url
from backlink_publisher.config import (
    DEFAULT_WORK_TEMPLATES,
    ThreeUrlConfig,
    load_config,
    save_config,
)
from backlink_publisher.content.scraper import fetch_work_metadata

from ..helpers.url_meta import (
    _derive_branded_pool,
    _derive_exact_pool,
    _derive_partial_pool,
    _verify_urls_or_error,
    fetch_full_tdk,
)
from ..services.work_themed_service import parse_lines as _parse_lines

# Autopilot interval guard rails (mirror the legacy route): 1h … 30d.
_MIN_INTERVAL = 3600
_MAX_INTERVAL = 2592000
_DEFAULT_INTERVAL = 86400


class SitesAPI:
    """Encapsulates work-themed site configuration + autopilot lifecycle."""

    # ── read: per-site list ───────────────────────────────────────────────

    def list_sites(self) -> list[dict[str, Any]]:
        """All configured sites with live autopilot status (newest-config last).

        Each row: ``{label, main_url, autopilot_enabled, autopilot_interval,
        alert_pending, next_run_time_iso}``. The next-run lookup is fail-open —
        a missing/unstarted scheduler leaves ``next_run_time_iso`` null, never
        raises (mirrors the legacy route's defensive scheduler access).
        """
        import webui_store as _ws

        cfg = load_config()
        sched_settings = _ws.schedule_store.load()
        autopilot_targets = sched_settings.get("autopilot_targets", {})
        sched_mod = sys.modules.get("webui_app.scheduler")

        sites: list[dict[str, Any]] = []
        for label, entry in sorted(cfg.target_three_url.items()):
            ap_cfg = autopilot_targets.get(entry.main_url, {})
            ap_enabled = bool(ap_cfg.get("enabled", False))
            next_run_time_iso = self._next_run_iso(sched_mod, entry.main_url) if ap_enabled else None
            sites.append({
                "label": label,
                "main_url": entry.main_url,
                "autopilot_enabled": ap_enabled,
                "autopilot_interval": int(ap_cfg.get("interval_seconds", _DEFAULT_INTERVAL)),
                "alert_pending": bool(ap_cfg.get("alert_pending", False)),
                "next_run_time_iso": next_run_time_iso,
            })
        return sites

    @staticmethod
    def _next_run_iso(sched_mod: Any, site_url: str) -> str | None:
        """Best-effort APScheduler next-run ISO string for a site, or None."""
        if sched_mod is None or getattr(sched_mod, "_scheduler", None) is None:
            return None
        try:
            job = sched_mod._scheduler.get_job(sched_mod._autopilot_job_id(site_url))
        except Exception:
            return None
        if job is not None and job.next_run_time is not None:
            return job.next_run_time.isoformat()
        return None

    # ── read: form prefill for one domain ─────────────────────────────────

    def get_form(self, domain: str) -> dict[str, Any] | None:
        """Prefill payload for editing an existing site, or None if unknown."""
        domain = (domain or "").rstrip("/")
        if not domain:
            return None
        entry = load_config().target_three_url.get(domain)
        if entry is None:
            return None
        return {
            "main_url": entry.main_url,
            "list_url": entry.list_url,
            "work_urls": "\n".join(entry.work_urls),
            "branded_pool": "\n".join(entry.branded_pool),
            "partial_pool": "\n".join(entry.partial_pool),
            "exact_pool": "\n".join(entry.exact_pool),
            "work_anchor_templates": "\n".join(entry.work_anchor_templates),
            "count": "10",
            "insecure_tls": entry.insecure_tls,
        }

    # ── write: save three-URL config (validation + server-side derivation) ─

    def save_three_url(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate, derive missing fields, and persist a three-URL site entry.

        Returns one of:
          * ``{"ok": False, "errors": {field: msg}}`` — validation failed,
            nothing written (caller → 422).
          * ``{"ok": True, "saved_domain": key, "autofilled": [fields]}`` —
            persisted; ``autofilled`` lists the server-derived fields.
        """
        insecure_tls = bool(raw.get("insecure_tls"))
        fields, errors = self._validate_three_url(raw)
        if errors:
            return {"ok": False, "errors": errors}

        autofilled = self._derive_missing_fields(fields, insecure_tls)
        if autofilled:
            plan_logger.recon(
                "sites_save_autofilled", main_url=fields["main_url"], fields=autofilled
            )

        entry = ThreeUrlConfig(
            main_url=fields["main_url"], list_url=fields["list_url"],
            branded_pool=fields["branded_pool"], partial_pool=fields["partial_pool"],
            exact_pool=fields["exact_pool"], work_urls=fields["work_urls"],
            work_anchor_templates=fields["templates"], insecure_tls=insecure_tls,
        )
        domain_key = fields["main_url"].rstrip("/")
        cfg = load_config()
        merged = dict(cfg.target_three_url)
        merged[domain_key] = entry
        save_config(cfg, target_anchor_keywords=None, target_three_url=merged)

        return {"ok": True, "saved_domain": domain_key, "autofilled": autofilled}

    @staticmethod
    def _validate_three_url(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        """Shape-validate + reachability-gate the form. Returns (fields, errors).

        ``fields`` holds the parsed values (URLs normalised, pools split to lists,
        ``templates`` defaulted); ``errors`` is per-field and non-empty iff the
        submission should be rejected before any persistence/derivation.
        """
        errors: dict[str, str] = {}

        main_url = validate_main_domain_url(str(raw.get("main_url") or "").strip())
        if not main_url:
            errors["main_url"] = "必须 https + host-root + 单一尾斜杠（例：https://your-site.com/）"

        list_url = ""
        if str(raw.get("list_url") or "").strip():
            validated = validate_https_url(str(raw.get("list_url")).strip())
            if validated:
                list_url = validated
            else:
                errors["list_url"] = "必须 https"

        work_urls: list[str] = []
        bad_work: list[str] = []
        for u in _parse_lines(raw.get("work_urls") or ""):
            normalized = validate_https_url(u)
            (work_urls if normalized else bad_work).append(normalized or u)
        if bad_work:
            errors["work_urls"] = f"以下 URL 必须 https：{', '.join(bad_work)}"

        # Reachability/anti-bot gate — only for fields that passed shape checks.
        for field, urls in (("main_url", [main_url]), ("list_url", [list_url]),
                            ("work_urls", work_urls)):
            if urls and urls[0] and field not in errors:
                _, gate_err = _verify_urls_or_error([u for u in urls if u], field)
                if gate_err:
                    errors[field] = gate_err

        fields = {
            "main_url": main_url,
            "list_url": list_url,
            "work_urls": work_urls,
            "branded_pool": _parse_lines(raw.get("branded_pool") or ""),
            "partial_pool": _parse_lines(raw.get("partial_pool") or ""),
            "exact_pool": _parse_lines(raw.get("exact_pool") or ""),
            "templates": _parse_lines(raw.get("work_anchor_templates") or "")
            or list(DEFAULT_WORK_TEMPLATES),
        }
        return fields, errors

    @staticmethod
    def _derive_missing_fields(fields: dict[str, Any], insecure_tls: bool) -> list[str]:
        """Fill any blank pool / list_url / work_urls IN PLACE (plan 006).

        Returns the names of the fields that were server-derived (for the
        "autofilled" notice). TDK fetch + sitemap discovery are best-effort.
        """
        derived: list[str] = []
        main_url = fields["main_url"]

        tdk: dict | None = None
        if not fields["branded_pool"] or not fields["partial_pool"]:
            try:
                tdk = fetch_full_tdk(main_url)
            except Exception as exc:  # noqa: BLE001 — derivation is best-effort
                plan_logger.warn("tdk_fetch_failed", url=main_url, reason=type(exc).__name__)

        if not fields["list_url"]:
            fields["list_url"] = main_url
            derived.append("list_url")
        if not fields["branded_pool"]:
            fields["branded_pool"] = _derive_branded_pool(main_url, tdk)
            derived.append("branded_pool")
        if not fields["partial_pool"]:
            fields["partial_pool"] = _derive_partial_pool(main_url, tdk)
            derived.append("partial_pool")
        if not fields["exact_pool"]:
            fields["exact_pool"] = _derive_exact_pool(main_url)
            derived.append("exact_pool")

        if not fields["work_urls"]:
            try:
                from backlink_publisher.content.scraper import fetch_work_urls_from_list
                discovered = fetch_work_urls_from_list(
                    fields["list_url"], main_url=main_url, max_candidates=10,
                    insecure_tls=insecure_tls,
                )
                if discovered:
                    fields["work_urls"] = discovered
                    derived.append("work_urls")
            except Exception as exc:  # noqa: BLE001 — discovery is best-effort
                plan_logger.warn(
                    "work_urls_discovery_failed",
                    main_url=main_url, list_url=fields["list_url"], reason=type(exc).__name__,
                )
        return derived

    @staticmethod
    def legacy_redirect_target(result: dict[str, Any]) -> str:
        """Build the legacy ``/sites?saved=…&autofilled=…`` redirect URL."""
        target = f"/sites?saved={result['saved_domain']}"
        if result.get("autofilled"):
            target += f"&autofilled={_quote(','.join(result['autofilled']))}"
        return target

    # ── write: autopilot toggle ───────────────────────────────────────────

    def set_autopilot(
        self, site_url: str, enabled: bool, interval_seconds: Any = _DEFAULT_INTERVAL,
    ) -> dict[str, Any]:
        """Enable/disable autopilot for a site, syncing the APScheduler job.

        Returns a neutral result:
          * ``error_code='MISSING_SITE_URL'`` — no site_url (caller → 422/400).
          * ``error_code='INVALID_INTERVAL'`` — non-int or out of 1h…30d range.
          * ``error_code='SCHEDULER_SYNC_FAILED'`` — job (un)registration threw;
            the store mutation was ROLLED BACK (caller → 502/500). ``detail``
            carries the exception text.
          * ``{"ok": True, "site_url", "enabled", "next_run_time", "last_run"}``.
        """
        import webui_store as _ws

        site_url = (site_url or "").strip()
        if not site_url:
            return {"ok": False, "error_code": "MISSING_SITE_URL"}

        enabled = bool(enabled)
        try:
            interval = int(interval_seconds)
        except (TypeError, ValueError):
            return {"ok": False, "error_code": "INVALID_INTERVAL",
                    "detail": "interval_seconds must be an integer"}
        if enabled and not (_MIN_INTERVAL <= interval <= _MAX_INTERVAL):
            return {"ok": False, "error_code": "INVALID_INTERVAL",
                    "detail": "interval_seconds must be between 3600 (1h) and 2592000 (30d)"}

        current = _ws.schedule_store.load().get("autopilot_targets", {})
        was_present = site_url in current
        snapshot = dict(current[site_url]) if was_present else None

        def _update(settings):
            targets = dict(settings.get("autopilot_targets", {}))
            site_cfg = dict(targets.get(site_url, {}))
            site_cfg["enabled"] = enabled
            if enabled:
                site_cfg["interval_seconds"] = interval
            targets[site_url] = site_cfg
            return {**settings, "autopilot_targets": targets}

        _ws.schedule_store.update(_update)

        next_run_time = None
        try:
            sched_mod = sys.modules.get("webui_app.scheduler")
            if enabled:
                sched_mod._register_autopilot_job(site_url, interval)
                next_run_time = self._next_run_iso(sched_mod, site_url)
            else:
                try:
                    sched_mod._scheduler.remove_job(sched_mod._autopilot_job_id(site_url))
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 — roll back only this site's cfg
            def _rollback(s):
                targets = dict(s.get("autopilot_targets", {}))
                if was_present:
                    targets[site_url] = snapshot
                else:
                    targets.pop(site_url, None)
                return {**s, "autopilot_targets": targets}
            _ws.schedule_store.update(_rollback)
            return {"ok": False, "error_code": "SCHEDULER_SYNC_FAILED", "detail": str(exc)}

        updated = _ws.schedule_store.load().get("autopilot_targets", {}).get(site_url, {})
        return {
            "ok": True,
            "site_url": site_url,
            "enabled": enabled,
            "next_run_time": next_run_time,
            "last_run": updated.get("last_run"),
        }

    # ── read: scrape preview ──────────────────────────────────────────────

    def scrape_preview(self, url: str) -> dict[str, Any]:
        """Fetch title/description/h1 for a work URL. Always a neutral dict.

        ``{"status": "ok", title, description, h1}`` or ``{"status": "error",
        reason}``. Network/parse failures are reported as ``error``, never raised.
        """
        url = (url or "").strip()
        if not url:
            return {"status": "error", "reason": "missing url param"}
        try:
            meta = fetch_work_metadata(url)
        except InputValidationError as exc:
            return {"status": "error", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 — surface as error, never 500
            return {"status": "error", "reason": type(exc).__name__}
        if meta is None:
            return {"status": "error", "reason": "no metadata extracted"}
        return {
            "status": "ok",
            "title": meta.title,
            "description": meta.description,
            "h1": meta.h1,
        }

    # ── read: side-panel widgets (plan-gap weekly + citation-share alert) ──

    def widgets(self) -> dict[str, Any]:
        """Read-only side-panel data: plan-gap summary + citation-share alert."""
        return {
            "plan_gap": self.plan_gap_summary(),
            "citation_alert": self.citation_share_alert(),
        }

    @staticmethod
    def plan_gap_summary(path=None) -> dict[str, Any]:
        """Summarise the latest plan-gap seed JSONL for display. Fail-soft."""
        import json
        import os
        from datetime import datetime, timezone
        from pathlib import Path

        path = Path(path) if path is not None else (
            Path(__file__).resolve().parents[2] / "logs" / "plan-gap-latest.json"
        )
        if not path.exists():
            return {"status": "missing"}
        try:
            mtime = os.path.getmtime(path)
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except json.JSONDecodeError:
            return {"status": "invalid", "error": "JSONL 格式損毀"}
        except OSError:
            return {"status": "invalid", "error": "無法讀取 plan-gap 結果"}

        targets = {
            row.get("target_url")
            for row in rows
            if isinstance(row, dict) and row.get("target_url")
        }
        triggered_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return {
            "status": "ok",
            "candidate_count": len(rows),
            "target_count": len(targets),
            "triggered_at": triggered_at,
        }

    @staticmethod
    def citation_share_alert() -> dict[str, Any] | None:
        """Citation-share alert info from logs/citation-share-alert.json. Fail-open."""
        import json
        from pathlib import Path

        try:
            path = Path(__file__).resolve().parents[2] / "logs" / "citation-share-alert.json"
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return {"ts": data.get("ts", "")}
        except Exception:  # noqa: BLE001 — fail-open
            return None
