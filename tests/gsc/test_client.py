"""Tests for gsc.client.GscClient (Plan 2026-06-16-003 Unit 1)."""

from __future__ import annotations

__tier__ = "unit"

import json
from pathlib import Path
import stat
from unittest.mock import MagicMock, patch

import pytest

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher.gsc.client import GscClient


@pytest.fixture()
def sa_json(tmp_path: Path) -> Path:
    """Minimal service-account JSON at 0o600."""
    p = tmp_path / "sa.json"
    p.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "test",
                "private_key_id": "k1",
                "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA==\n-----END RSA PRIVATE KEY-----\n",
                "client_email": "test@project.iam.gserviceaccount.com",
                "client_id": "123",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
    )
    p.chmod(0o600)
    return p


def test_build_happy_path(sa_json: Path) -> None:
    client = GscClient(str(sa_json), "sc-domain:example.com")
    assert client._property_url == "sc-domain:example.com"


def test_missing_credential_file(tmp_path: Path) -> None:
    with pytest.raises(ExternalServiceError, match="not found"):
        GscClient(str(tmp_path / "missing.json"), "sc-domain:example.com")


def test_empty_property_url_raises(sa_json: Path) -> None:
    with pytest.raises(ValueError, match="property_url must not be empty"):
        GscClient(str(sa_json), "")


def test_bad_file_mode_still_constructs(sa_json: Path) -> None:
    # Bad mode triggers a warning but does NOT prevent construction.
    sa_json.chmod(0o644)
    client = GscClient(str(sa_json), "sc-domain:example.com")
    assert client._property_url == "sc-domain:example.com"


def test_search_analytics_query_happy_path(sa_json: Path) -> None:
    mock_response = {"rows": [{"keys": ["https://example.com/page"], "clicks": 5}]}

    mock_service = MagicMock()
    mock_service.searchanalytics().query().execute.return_value = mock_response

    with (
        patch("google.oauth2.service_account.Credentials.from_service_account_file"),
        patch("googleapiclient.discovery.build", return_value=mock_service),
    ):
        client = GscClient(str(sa_json), "sc-domain:example.com")
        result = client.search_analytics_query(
            {"startDate": "2026-01-01", "endDate": "2026-01-31", "dimensions": ["page"]}
        )

    assert result == mock_response


def test_search_analytics_api_403(sa_json: Path) -> None:
    from googleapiclient.errors import HttpError

    http_err = HttpError(resp=MagicMock(status=403), content=b"Forbidden")
    mock_service = MagicMock()
    mock_service.searchanalytics().query().execute.side_effect = http_err

    with (
        patch("google.oauth2.service_account.Credentials.from_service_account_file"),
        patch("googleapiclient.discovery.build", return_value=mock_service),
    ):
        client = GscClient(str(sa_json), "sc-domain:example.com")
        with pytest.raises(ExternalServiceError, match="403"):
            client.search_analytics_query({})
