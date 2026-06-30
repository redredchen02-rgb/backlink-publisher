"""Thin GSC Search Console API client (Plan 2026-06-16-003 Unit 1).

Contract:
* ``GscClient`` wraps the Search Analytics v1 endpoint.
* Credentials loaded from a service account JSON file (should be 0o600; a
  warning is logged if the mode differs — file is still loaded).
* All ``googleapiclient`` imports are lazy (inside method bodies) to prevent
  discovery-cache side effects at import time.
* 4xx API errors are re-raised as ``ExternalServiceError``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.logger import get_logger
from backlink_publisher._util.permissions import check_0600

log = get_logger("gsc.client")

_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class GscClient:
    """Authenticated GSC Search Analytics client."""

    def __init__(self, credential_path: str, property_url: str) -> None:
        """Build an authenticated client.

        Parameters
        ----------
        credential_path:
            Path to the service-account JSON key file.  Should be 0o600; a
            warning is logged if not, but the file is still loaded.
        property_url:
            GSC property string, e.g. ``sc-domain:example.com``.

        Raises
        ------
        ExternalServiceError
            If the credential file is missing or unreadable.
        ValueError
            If ``property_url`` is empty.
        """
        if not property_url:
            raise ValueError("property_url must not be empty")

        cred_path = Path(credential_path)
        if not cred_path.exists():
            log.debug(f"gsc: credential_path={credential_path!r} not found")
            raise ExternalServiceError(
                "GSC credential file not found — check [gsc].credential_path in config.toml"
            )

        check_0600(cred_path, label="GSC credentials")

        self._credential_path = str(cred_path)
        self._property_url = property_url

    def search_analytics_query(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """Execute a Search Analytics query against the configured property.

        Parameters
        ----------
        request_body:
            Full request body dict (``startDate``, ``endDate``, ``dimensions``,
            ``dimensionFilterGroups``, etc.).

        Returns
        -------
        dict
            Raw API response (``{"rows": [...], ...}``).

        Raises
        ------
        ExternalServiceError
            On 4xx/5xx responses.
        """
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            import httplib2
        except ImportError as exc:
            raise ExternalServiceError(
                f"google-api-python-client not installed: {exc}"
            ) from exc

        try:
            credentials = service_account.Credentials.from_service_account_file(
                self._credential_path,
                scopes=[_GSC_SCOPE],
            )
            http = credentials.authorize(httplib2.Http(timeout=30))
            service = build("searchconsole", "v1", http=http)
            response = (
                service.searchanalytics()
                .query(siteUrl=self._property_url, body=request_body)
                .execute()
            )
            return response or {}
        except HttpError as exc:
            raise ExternalServiceError(
                f"GSC API error {exc.status_code}: {exc.reason}"
            ) from exc
        except Exception as exc:
            raise ExternalServiceError(f"GSC request failed: {exc}") from exc
