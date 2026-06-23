"""Pipeline API layer — structured wrappers for CLI invocation, draft CRUD,
and history operations.  Phase A extraction (Plan 2026-05-25-003).

Usage from routes::

    from ..api.pipeline_api import PipelineAPI, PipeResult
    api = PipelineAPI()
    result = api.plan(seed_json)
    if not result.success:
        ...
"""

from .pipeline_api import PipelineAPI, PipeResult
from .drafts_api import DraftAPI
from .history_api import HistoryAPI
from .sites_api import SitesAPI
from .campaign_api import CampaignAPI
from .channel_bind_api import BindSaveResult, ChannelBindAPI
from .bind_api import BindAPI, BindResult
from .oauth_api import OAuthAPI, OAuthResult
from .llm_settings_api import LlmSaveResult, LlmSettingsAPI
from .llm_diagnostics_api import DiagnosticResult, LlmDiagnosticsAPI
from .image_gen_diagnostics_api import ImageGenDiagnosticsAPI
from .medium_login_api import MediumLoginAPI, MediumLoginResult
from .global_settings_api import GlobalSettingsAPI, GlobalSettingsResult
from .channel_overview_api import ChannelOverviewAPI
from .channel_forms_api import ChannelFormsAPI
from .velog_login_api import VelogLoginAPI, VelogLoginResult
from .blogger_settings_api import BloggerSettingsAPI, BlogIdsResult

__all__ = [
    "PipelineAPI",
    "PipeResult",
    "DraftAPI",
    "HistoryAPI",
    "SitesAPI",
    "CampaignAPI",
    "ChannelBindAPI",
    "BindSaveResult",
    "BindAPI",
    "BindResult",
    "OAuthAPI",
    "OAuthResult",
    "LlmSettingsAPI",
    "LlmSaveResult",
    "LlmDiagnosticsAPI",
    "DiagnosticResult",
    "ImageGenDiagnosticsAPI",
    "MediumLoginAPI",
    "MediumLoginResult",
    "GlobalSettingsAPI",
    "GlobalSettingsResult",
    "ChannelOverviewAPI",
    "ChannelFormsAPI",
    "VelogLoginAPI",
    "VelogLoginResult",
    "BloggerSettingsAPI",
    "BlogIdsResult",
]
