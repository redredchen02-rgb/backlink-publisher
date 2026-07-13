"""OnboardingAPI — first-run guide status, transport-neutral (Plan 2026-07-09-001).

Computes, on every read, whether each onboarding step is complete by consulting
the SAME single sources the rest of the app uses (channel binding status, LLM
config, keyword pools, campaigns, publish history). No step state is stored here
— only the operator's 'dismissed' preference lives in ``webui_store``. This keeps
the wizard self-healing: completing a step through any other page flips it to
done, and the guide can never show a step as complete that isn't.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OnboardingStep:
    """One onboarding step as served to the SPA. ``done`` is computed live."""

    id: str
    title: str
    rationale: str
    optional: bool
    cta: str
    done: bool


class OnboardingAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def status(self) -> dict:
        """Aggregate the 5-step happy path; each step's ``done`` is derived live."""
        from webui_store import campaign_store, history_store, onboarding_store

        from ..api.channel_overview_api import ChannelOverviewAPI
        from ..api.global_settings_api import GlobalSettingsAPI
        from ..services import app_meta

        # 1) Connect a publishing channel — any bound platform counts.
        channels = ChannelOverviewAPI().list_channels()
        step_connect = any(bool(c.get("bound")) for c in channels)

        # 2) Configure LLM — mirrors /api/v1/app-config's llm_configured signal.
        llm_cfg = bool(app_meta.pro_status_payload().get("configured", False))

        # 3) Add target sites + anchor keyword pools (requires a Blogger Blog-ID
        #    mapping first, which is part of step 1's blogids card).
        kp = GlobalSettingsAPI().get_keywords()
        targets = kp.get("targets") or []
        pools = kp.get("pools") or {}
        step_targets = bool(targets) and any(pools.get(t) for t in targets)

        # 4) Create the first campaign.
        step_campaign = bool(campaign_store.list())

        # 5) Publish the first article — any history record marked published.
        history = history_store.load() or []
        step_published = any(
            isinstance(it, dict) and it.get("status") == "published" for it in history
        )

        dismissed = onboarding_store.is_dismissed()
        steps = [
            OnboardingStep(
                "connect_channel",
                "連接你的第一個發布渠道",
                "先把文章發布到哪裡——連接 Medium / Velog / Blogger 等至少一個平台。",
                False,
                "/settings#sec-channels",
                step_connect,
            ),
            OnboardingStep(
                "configure_llm",
                "配置 LLM（建議）",
                "啟用 AI 自動生成外鏈文章與封面圖，大幅減少手寫工作量。",
                True,
                "/settings#sec-ai",
                llm_cfg,
            ),
            OnboardingStep(
                "add_targets",
                "添加目標站點與錨文本池",
                "設定要推廣的目標站與錨文本關鍵詞，文章才會帶上正確的外鏈。",
                False,
                "/settings#sec-keywords",
                step_targets,
            ),
            OnboardingStep(
                "create_campaign",
                "建立你的第一個 Campaign",
                "把一批目標網址匯整成 Campaign，批次規劃與發布外鏈。",
                False,
                "/batch-campaign",
                step_campaign,
            ),
            OnboardingStep(
                "publish_first",
                "發布你的第一篇文章",
                "實際發出第一篇外鏈文章，完成首次端到端發布。",
                False,
                "/publish",
                step_published,
            ),
        ]
        required_done = all(s.done for s in steps if not s.optional)
        return {
            "dismissed": dismissed,
            "all_done": required_done,
            "steps": [vars(s) for s in steps],
        }

    def dismiss(self) -> None:
        """Mark the guide as dismissed so it no longer auto-shows."""
        from webui_store import onboarding_store

        onboarding_store.set_dismissed(True)

    def reset(self) -> None:
        """Clear the dismissed flag (used by tests / demos to re-show the guide)."""
        from webui_store import onboarding_store

        onboarding_store.set_dismissed(False)
