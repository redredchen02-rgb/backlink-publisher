"""CampaignWorker — dedicated in-process worker pool for campaign execution.

Runs alongside APScheduler without interfering. Campaigns execute sequentially
within the worker (one at a time) but don't block the APScheduler pool.

Plan: docs/plans/2026-06-02-001-feat-batch-optimization-plan.md U5.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import logging
from typing import Any

_log = logging.getLogger(__name__)


class CampaignWorker:
    """In-process campaign executor.

    Accepts one campaign at a time.  New submissions while a campaign is running
    are rejected with ``AlreadyRunningError``.
    """

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running: dict[str, Future] = {}

    # ── Public API ─────────────────────────────────────────────────────────

    def start_campaign(self, campaign_id: str, cfg: dict[str, Any]) -> None:
        """Submit a campaign for background execution.

        Args:
            campaign_id: The ``CampaignStore`` campaign id.
            cfg: Campaign configuration dict with keys:
                - ``platforms``: list of platform slugs
                - ``mode``: "draft" or "publish"
                - ``cap``: optional int
                - ``seed_delay``: optional int (seconds)

        Raises:
            AlreadyRunningError: if a campaign is already in progress.
        """
        if self.is_running():
            raise AlreadyRunningError(
                f"A campaign is already in progress. "
                f"Running campaign: {next(iter(self._running), 'unknown')}"
            )
        future = self._executor.submit(
            _execute_campaign, campaign_id, cfg,
        )
        self._running[campaign_id] = future

    def get_status(self, campaign_id: str) -> dict[str, Any] | None:
        """Return the campaign's current state from CampaignStore.

        Returns ``None`` if the campaign id is unknown.
        """
        from webui_store import campaign_store
        campaign = campaign_store.get(campaign_id)
        if campaign is None:
            return None
        result = dict(campaign)
        future = self._running.get(campaign_id)
        if future is not None:
            result["_running"] = future.running()
            result["_done"] = future.done()
        else:
            result["_running"] = False
            result["_done"] = True
        return result

    def cancel_campaign(self, campaign_id: str) -> bool:
        """Attempt to cancel a running campaign.

        Returns ``True`` if cancellation was successful, ``False`` if no
        campaign with that id is running or it could not be cancelled.
        """
        future = self._running.get(campaign_id)
        if future is None or future.done():
            return False
        cancelled = future.cancel()
        if cancelled:
            self._running.pop(campaign_id, None)
            from webui_store import campaign_store
            campaign_store.update_status(
                campaign_id, status="failed",
            )
        return cancelled

    def is_running(self) -> bool:
        """Return ``True`` if any campaign is currently executing."""
        # Prune completed futures.
        done_ids = [
            cid for cid, f in self._running.items()
            if f.done()
        ]
        for cid in done_ids:
            self._running.pop(cid, None)
        return bool(self._running)

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the worker pool."""
        self._executor.shutdown(wait=wait)


class AlreadyRunningError(RuntimeError):
    """Raised when ``start_campaign`` is called while a campaign runs."""


# ── Internal execution ───────────────────────────────────────────────────

def _execute_campaign(campaign_id: str, cfg: dict[str, Any]) -> None:
    """Execute a campaign: run spray-backlinks per seed and collect results.

    Runs entirely inside a ThreadPoolExecutor thread. Updates CampaignStore
    as each seed completes.
    """
    from webui_store import campaign_store

    try:
        campaign_store.update_status(campaign_id, status="running")

        campaign = campaign_store.get(campaign_id)
        if campaign is None:
            _log.error("campaign %s not found — aborting", campaign_id)
            campaign_store.update_status(campaign_id, status="failed")
            return

        seeds = campaign.get("seeds", [])
        platforms = cfg.get("platforms", [])
        mode = cfg.get("mode", "draft")
        cap = cfg.get("cap")
        seed_delay = cfg.get("seed_delay", 0)

        total = len(seeds)
        for idx, seed in enumerate(seeds):
            campaign_store.update_seed_status(
                campaign_id, idx, status="processing",
            )

            # Build seed JSONL from the seed dict.
            seed_text = seed.get("seed_text", "")
            seed_row = json.dumps({
                "seed_text": seed_text,
                "platforms": platforms,
                "cap": cap,
                "mode": mode,
            })

            try:
                # Run spray-backlinks for this single seed.
                _run_spray_for_seed(seed_row, platforms, mode, cap)
                campaign_store.update_seed_status(
                    campaign_id, idx,
                    status="success",
                    draft_count=1,
                    published_count=1 if mode == "publish" else 0,
                )
            except Exception as exc:
                _log.warning("seed %d failed: %s", idx, exc)
                campaign_store.update_seed_status(
                    campaign_id, idx,
                    status="failed",
                    error=str(exc),
                )

            # Inter-seed delay.
            if idx < total - 1 and seed_delay and seed_delay > 0:
                import time
                _log.info("waiting %ds before next seed", seed_delay)
                time.sleep(seed_delay)

        # Check final status — if any seed succeeded, campaign is in draft_review
        # (draft mode) or completed (publish mode).
        final_campaign = campaign_store.get(campaign_id)
        if final_campaign is None:
            return
        seeds_final = final_campaign.get("seeds", [])
        any_success = any(
            s.get("status") == "success" for s in seeds_final
        )
        any_failed = any(
            s.get("status") == "failed" for s in seeds_final
        )

        if any_success:
            final_status = "draft_review" if mode == "draft" else "completed"
        elif any_failed:
            final_status = "failed"
        else:
            final_status = "completed"

        campaign_store.update_status(
            campaign_id,
            status=final_status,
        )
        _log.info(
            "campaign %s completed: status=%s", campaign_id, final_status,
        )

    except Exception as exc:
        _log.error("campaign %s crashed: %s", campaign_id, exc)
        try:
            campaign_store.update_status(campaign_id, status="failed")
        except Exception:
            _log.exception("failed to mark campaign %s as failed", campaign_id)


def _run_spray_for_seed(
    seed_jsonl: str,
    platforms: list[str],
    mode: str,
    cap: int | None,
) -> None:
    """Run spray-backlinks for a single seed row.

    Uses the in-process PipelineAPI to invoke the spray pipeline (plan →
    validate → publish) for this one seed.
    """
    from .api import PipelineAPI
    api = PipelineAPI()

    platform_csv = ",".join(platforms)
    # Build seed JSONL with full context.
    seed_obj = json.loads(seed_jsonl)

    # Inject platform info.
    seed_obj["platform"] = platform_csv
    seed_obj["publish_mode"] = mode
    seed_jsonl_with_platform = json.dumps(seed_obj, ensure_ascii=False)

    # Step 1: plan
    plan_res = api.plan(seed_jsonl_with_platform)
    if not plan_res.success:
        raise RuntimeError(f"plan stage failed: {plan_res.error}")

    # Step 2: validate
    val_res = api.validate(plan_res.stdout, no_check_urls=True)
    if not val_res.success:
        raise RuntimeError(f"validation stage failed: {val_res.error}")

    # Step 3: publish/burst dispatch.
    # For campaigns we always use burst dispatch (not dry-run).
    pub_res = api.publish(val_res.stdout, platform_csv, mode)
    if not pub_res.success:
        raise RuntimeError(f"publish stage failed: {pub_res.error}")
