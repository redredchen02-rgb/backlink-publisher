"""Tests for VelogGraphQLAdapter (Unit 4).

Covers:
- _slugify
- _effective_cap: phase 1 / phase 2 date gate
- _read_count / _write_count: happy, UTC rollover, corrupt file
- _save_null_artifact
- publish(): happy path, silent-drop retry, daily cap, cookie expired
"""
from __future__ import annotations

__tier__ = "unit"
from datetime import datetime, timezone, UTC
import json
import os
from pathlib import Path
import stat
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from backlink_publisher._util.errors import (
    AuthExpiredError,
    ContentRejectedError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.config import Config
from backlink_publisher.config.types import VelogConfig
from backlink_publisher.publishing.adapters.velog_graphql import (
    _effective_cap,
    _read_count,
    _save_null_artifact,
    _slugify,
    _write_count,
    VelogGraphQLAdapter,
)

# ── _slugify ──────────────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_punctuation_stripped(self):
        assert _slugify("Test Post #1!") == "test-post-1"

    def test_multiple_spaces(self):
        assert _slugify("  foo   bar  ") == "foo-bar"

    def test_empty_returns_post(self):
        assert _slugify("") == "post"

    def test_hyphens_collapsed(self):
        assert _slugify("a - b") == "a-b"


# ── _effective_cap ────────────────────────────────────────────────────────────

class TestEffectiveCap:
    def test_before_unlock_returns_initial(self):
        past = datetime(2020, 1, 1, tzinfo=UTC)
        with patch(
            "backlink_publisher.publishing.adapters.velog_graphql.UNLOCK_DATE_UTC",
            datetime(2099, 1, 1, tzinfo=UTC),
        ):
            cap = _effective_cap()
        assert cap == 5  # _VELOG_DAILY_CAP_INITIAL

    def test_after_unlock_returns_prod(self):
        with patch(
            "backlink_publisher.publishing.adapters.velog_graphql.UNLOCK_DATE_UTC",
            datetime(2020, 1, 1, tzinfo=UTC),
        ):
            cap = _effective_cap()
        assert cap == 30  # _VELOG_DAILY_CAP_PROD


# ── _read_count / _write_count ────────────────────────────────────────────────

class TestCountFile:
    def test_missing_file_returns_zero(self, tmp_path):
        count, last = _read_count(tmp_path / "no-file.json")
        assert count == 0
        assert last == 0.0

    def test_today_returns_count(self, tmp_path):
        p = tmp_path / "count.json"
        from datetime import datetime
        today = datetime.now(UTC).date().isoformat()
        p.write_text(json.dumps({"date_utc": today, "count": 3, "last_publish_at": 9999.0}))
        count, last = _read_count(p)
        assert count == 3
        assert last == 9999.0

    def test_read_and_write_use_utc_date_not_local(self, tmp_path, monkeypatch):
        """Regression: ``_read_count`` and ``_write_count`` must derive the
        ``date_utc`` field from UTC, not the host's local timezone.

        Prior code used ``date.today()`` which returns the local-time date.
        On a machine in UTC+9 (KST), at 2026-05-19T22:00 UTC the local
        date is already 2026-05-20; the cap would reset 9 hours early
        relative to the documented UTC boundary. Conversely, in UTC-8,
        the cap would still report 2026-05-19 hours after UTC midnight.

        Simulates a UTC+9 host at 2026-05-19T23:30Z (local = 2026-05-20):
        - UTC-derived implementation writes ``date_utc=2026-05-19``.
        - ``date.today()``-based implementation writes ``date_utc=2026-05-20``.
        """
        from datetime import datetime

        from backlink_publisher.publishing.adapters import velog_graphql

        UTC_DATE = "2026-05-19"
        LOCAL_DATE_IN_FAKE_KST = "2026-05-20"

        class _FakeDate:
            """Stand-in for ``datetime.date`` matching the bug's local-time semantics."""

            @classmethod
            def today(cls):
                from datetime import date as _real_date
                return _real_date.fromisoformat(LOCAL_DATE_IN_FAKE_KST)

        class _FakeDatetime(datetime):
            """Stand-in for ``datetime.datetime`` returning the correct UTC instant."""

            @classmethod
            def now(cls, tz=None):
                base = datetime(2026, 5, 19, 23, 30, 0, tzinfo=UTC)
                if tz is None:
                    return _FakeDate.today()  # local naive
                return base.astimezone(tz)

        # Patch both names that either implementation might use. The
        # current fix only touches ``datetime``; the bug version reads
        # ``date.today()``. raising=False so the test passes against
        # either source state.
        monkeypatch.setattr(velog_graphql, "datetime", _FakeDatetime)
        monkeypatch.setattr(velog_graphql, "date", _FakeDate, raising=False)

        p = tmp_path / "count.json"
        _write_count(p, 5, 1.0)
        body = json.loads(p.read_text())
        assert body["date_utc"] == UTC_DATE, (
            f"date_utc={body['date_utc']!r} — derived from local time "
            "instead of UTC. Cap reset boundary must be UTC midnight."
        )

        # And the corresponding read on the same UTC day must NOT reset.
        count, _ = _read_count(p)
        assert count == 5

    def test_stale_date_resets(self, tmp_path):
        p = tmp_path / "count.json"
        p.write_text(json.dumps({"date_utc": "2020-01-01", "count": 30, "last_publish_at": 1.0}))
        count, last = _read_count(p)
        assert count == 0
        assert last == 0.0

    def test_corrupt_json_resets(self, tmp_path):
        p = tmp_path / "count.json"
        p.write_text("garbage{")
        count, last = _read_count(p)
        assert count == 0

    def test_write_then_read_roundtrip(self, tmp_path):
        p = tmp_path / "count.json"
        _write_count(p, 7, 1234567890.0)
        count, last = _read_count(p)
        assert count == 7
        assert last == 1234567890.0
        # File must be 0600
        assert stat.S_IMODE(p.stat().st_mode) == 0o600


# ── VelogGraphQLAdapter.publish() ─────────────────────────────────────────────

def _make_config(tmp_path: Path) -> Config:
    cookies_file = tmp_path / "velog-cookies.json"
    cookies_file.write_text(json.dumps({
        "cookies": [
            {"name": "access_token", "value": "AT_TEST"},
            {"name": "refresh_token", "value": "RT_TEST"},
        ]
    }))
    os.chmod(cookies_file, 0o600)
    return Config(velog=VelogConfig(cookies_path=cookies_file))


PAYLOAD = {
    "id": "test-001",
    "title": "Test Velog Post",
    "content_markdown": "# Hello\n\nCheck out [this link](https://example.com).",
    "tags": ["test", "spike"],
    "target_url": "https://example.com",
}


def _mock_success_response(url_slug="test-velog-post", username="redredchen01"):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {
        "data": {
            "writePost": {
                "id": "post-uuid-123",
                "user": {"id": "user-uuid", "username": username, "__typename": "User"},
                "url_slug": url_slug,
                "__typename": "Post",
            }
        }
    }
    return resp


def _mock_null_response():
    """Simulates silent-drop (access_token expired, refresh happening)."""
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = {"data": {"writePost": None}}
    return resp


def _mock_429_response():
    """HTTP 429 — a pre-create rate-limit rejection. _do_post raises
    _TransientHTTPError(429) for this, which IS retryable (the server rejected
    the request before creating anything)."""
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 429
    return resp


class TestVelogGraphQLAdapterPublish:
    def _patch_lock_and_count(self, tmp_path):
        """Context manager patches that bypass fcntl locking for tests."""
        import contextlib

        @contextlib.contextmanager
        def _patches():
            with patch(
                "backlink_publisher.publishing.adapters.velog_graphql._acquire_lock"
            ) as mock_lock, patch(
                "backlink_publisher.publishing.adapters.velog_graphql._release_lock"
            ), patch(
                "backlink_publisher.publishing.adapters.velog_graphql._read_count",
                return_value=(0, 0.0),
            ), patch(
                "backlink_publisher.publishing.adapters.velog_graphql._write_count"
            ), patch(
                "backlink_publisher.publishing.adapters.velog_graphql.random.uniform",
                return_value=0,  # skip jitter
            ):
                mock_lock.return_value = 99  # fake fd
                yield
        return _patches()

    def test_happy_path_publishes(self, tmp_path):
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.return_value = _mock_success_response()
                with patch(
                    "backlink_publisher.publishing.adapters.velog_graphql.verify_link_attributes",
                    return_value={"verification": "ok"},
                ):
                    result = adapter.publish(PAYLOAD, mode="publish", config=config)

        assert result.status == "published"
        assert result.platform == "velog"
        assert result.adapter == "velog-graphql"
        assert "redredchen01" in result.published_url
        assert result._provider_meta["post_id"] == "post-uuid-123"

    def test_silent_drop_retry_succeeds(self, tmp_path):
        """First call returns null, second (with new AT from Set-Cookie) succeeds."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_null_response(),        # first: silent-drop
                    _mock_success_response(),     # retry: success
                ]
                with patch(
                    "backlink_publisher.publishing.adapters.velog_graphql.verify_link_attributes",
                    return_value={"verification": "ok"},
                ):
                    result = adapter.publish(PAYLOAD, mode="publish", config=config)

        assert result.status == "published"
        assert sess.post.call_count == 2

    @pytest.mark.parametrize("exc_name", ["Timeout", "ConnectionError"])
    def test_create_network_error_not_retried(self, tmp_path, exc_name):
        """The WritePost mutation is a NON-IDEMPOTENT create — a Timeout/
        ConnectionError may mean velog already created the post, so it is sent
        exactly once and never retried on a network error (would duplicate).
        429 (a pre-create rejection) remains retryable; network errors do not.
        The 2nd response below is the duplicate that MUST NOT be sent."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    getattr(requests, exc_name)("net"),
                    _mock_success_response(),
                ]
                with pytest.raises(ExternalServiceError, match="unreachable"):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        assert sess.post.call_count == 1  # create mutation sent exactly once

    @pytest.mark.parametrize("exc_name", ["Timeout", "ConnectionError"])
    def test_silent_drop_retry_network_error_not_retried(self, tmp_path, exc_name):
        """The silent-drop RE-POST is also a non-idempotent create. If it hits a
        network error, it too is sent exactly once (no retry → no duplicate).
        First call returns null (silent-drop), the re-post raises the network
        error: total 2 posts (1 null + 1 failed-once), then ExternalServiceError."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_null_response(),           # first: silent-drop
                    getattr(requests, exc_name)("net"),  # re-post: network error
                    _mock_success_response(),        # duplicate that MUST NOT send
                ]
                with pytest.raises(ExternalServiceError, match="unreachable"):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        assert sess.post.call_count == 2  # null + one failed re-post, no retry

    def test_write_post_429_retried_and_recovers(self, tmp_path):
        """Parity with medium: a 429 on writePost IS retried (pre-create
        rejection), and the second attempt succeeds."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_429_response(),
                    _mock_success_response(),
                ]
                with patch(
                    "backlink_publisher.publishing.adapters.velog_graphql.verify_link_attributes",
                    return_value={"verification": "ok"},
                ):
                    result = adapter.publish(PAYLOAD, mode="publish", config=config)

        assert result.status == "published"
        assert sess.post.call_count == 2  # 429 retried, recovered

    def test_write_post_429_exhausted_raises_external_service_error(self, tmp_path):
        """429 on every attempt → retry exhausts → retry_transient_call re-raises
        _TransientHTTPError. It must surface as ExternalServiceError (the explicit
        except arm), not escape uncaught."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.return_value = _mock_429_response()
                with pytest.raises(ExternalServiceError, match="after retries"):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        assert sess.post.call_count == 3  # MAX_ATTEMPTS, then ExternalServiceError

    def test_null_after_retry_probe_dead_raises_auth_expired(self, tmp_path):
        """Both writePost calls return null; probe says cookie dead → AuthExpiredError."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        probe_resp = MagicMock()
        probe_resp.ok = True
        probe_resp.status_code = 200
        probe_resp.json.return_value = {"data": {"currentUser": None}}

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_null_response(),  # first writePost
                    _mock_null_response(),  # retry writePost
                    probe_resp,             # liveness probe
                ]

                with pytest.raises(AuthExpiredError, match="cookie dead"):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        assert sess.post.call_count == 3

    def test_null_after_retry_probe_alive_raises_content_rejected(self, tmp_path):
        """Both writePost calls return null; probe says cookie alive → ContentRejectedError."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        probe_resp = MagicMock()
        probe_resp.ok = True
        probe_resp.status_code = 200
        probe_resp.json.return_value = {
            "data": {"currentUser": {"id": "user-123", "username": "testuser"}}
        }

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_null_response(),  # first writePost
                    _mock_null_response(),  # retry writePost
                    probe_resp,             # liveness probe
                ]

                with pytest.raises(ContentRejectedError) as exc_info:
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        assert "cookie alive" in str(exc_info.value)
        assert exc_info.value.channel == "velog"

    def test_null_after_retry_probe_unreachable_fails_safe_to_auth_expired(self, tmp_path):
        """Probe network error → fail-safe: AuthExpiredError (not ContentRejectedError)."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_null_response(),               # first writePost
                    _mock_null_response(),               # retry writePost
                    requests.ConnectionError("timeout"), # probe fails
                ]

                with pytest.raises(AuthExpiredError, match="cookie dead"):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

    def test_null_after_retry_saves_artifact(self, tmp_path):
        """null-after-retry writes a debug artifact JSON with full response body."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        probe_resp = MagicMock()
        probe_resp.ok = True
        probe_resp.status_code = 200
        probe_resp.json.return_value = {"data": {"currentUser": None}}

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = [
                    _mock_null_response(),
                    _mock_null_response(),
                    probe_resp,
                ]
                with pytest.raises(AuthExpiredError):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        artifacts = list((config.config_dir / "debug").glob("velog-null-*.json"))
        assert len(artifacts) == 1
        data = json.loads(artifacts[0].read_text())
        assert data["adapter"] == "velog-graphql"
        assert data["article_id"] == PAYLOAD["id"]
        assert "response_body" in data

    def test_daily_cap_raises_dependency_error(self, tmp_path):
        """When count >= cap, DependencyError before any HTTP call."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        with patch(
            "backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session"
        ), patch(
            "backlink_publisher.publishing.adapters.velog_graphql._acquire_lock",
            return_value=99,
        ), patch(
            "backlink_publisher.publishing.adapters.velog_graphql._release_lock"
        ), patch(
            "backlink_publisher.publishing.adapters.velog_graphql._read_count",
            return_value=(5, time.time()),  # count == initial cap (5)
        ), patch(
            "backlink_publisher.publishing.adapters.velog_graphql._effective_cap",
            return_value=5,
        ):
            with pytest.raises(DependencyError, match="daily cap"):
                adapter.publish(PAYLOAD, mode="publish", config=config)

    def test_missing_cookies_raises_dependency_error(self, tmp_path):
        """Cookie file absent → DependencyError before HTTP."""
        config = Config(velog=VelogConfig(cookies_path=tmp_path / "no-file.json"))
        adapter = VelogGraphQLAdapter()

        with pytest.raises(DependencyError, match="velog-login"):
            adapter.publish(PAYLOAD, mode="publish", config=config)

    def test_url_slug_generated_from_title(self, tmp_path):
        """Published URL slug is derived from title, not null."""
        config = _make_config(tmp_path)
        adapter = VelogGraphQLAdapter()

        captured_payload = {}

        def _capture_and_respond(*args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            return _mock_success_response(url_slug="test-velog-post")

        with self._patch_lock_and_count(tmp_path):
            with patch("backlink_publisher.publishing.adapters.velog_graphql.SessionManager.get_session") as mock_get_session:
                sess = MagicMock()
                mock_get_session.return_value = sess
                sess.post.side_effect = _capture_and_respond
                with patch(
                    "backlink_publisher.publishing.adapters.velog_graphql.verify_link_attributes",
                    return_value={"verification": "ok"},
                ):
                    adapter.publish(PAYLOAD, mode="publish", config=config)

        slug_sent = captured_payload["variables"]["url_slug"]
        assert slug_sent is not None
        assert slug_sent != ""
        assert "test" in slug_sent  # derived from "Test Velog Post"


# ── _save_null_artifact ────────────────────────────────────────────────────────

class TestSaveNullArtifact:
    def test_writes_artifact_0600(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        config = _make_config(tmp_path)
        artifact = _save_null_artifact(
            resp_json={"data": {"writePost": None}},
            resp_headers={"content-type": "application/json"},
            article_id="abc123",
            config=config,
        )
        assert artifact is not None
        p = Path(artifact)
        assert p.exists()
        assert oct(p.stat().st_mode & 0o777) == "0o600"
        data = json.loads(p.read_text())
        assert data["article_id"] == "abc123"
        assert data["adapter"] == "velog-graphql"

    def test_captures_gql_errors_array(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        config = _make_config(tmp_path)
        resp_body = {
            "data": {"writePost": None},
            "errors": [{"message": "forbidden"}],
        }
        artifact = _save_null_artifact(resp_body, {}, "x1", config)
        data = json.loads(Path(artifact).read_text())
        assert data["gql_errors"] == [{"message": "forbidden"}]

    def test_returns_none_on_io_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
        config = _make_config(tmp_path)
        with patch(
            "backlink_publisher.publishing.adapters.velog_graphql.os.replace",
            side_effect=OSError("disk full"),
        ):
            result = _save_null_artifact({}, {}, "z1", config)
        # Should not raise — returns None on failure
        assert result is None


# ── ContentRejectedError taxonomy ─────────────────────────────────────────────

class TestContentRejectedErrorTaxonomy:
    def test_is_dependency_error_subclass(self):
        from backlink_publisher._util.errors import DependencyError
        assert issubclass(ContentRejectedError, DependencyError)

    def test_is_not_auth_expired_subclass(self):
        assert not issubclass(ContentRejectedError, AuthExpiredError)

    def test_exit_code_is_3(self):
        exc = ContentRejectedError(channel="velog", reason="x")
        assert exc.exit_code == 3

    def test_message_contains_channel_and_reason(self):
        exc = ContentRejectedError(channel="velog", reason="slug collision")
        assert "velog" in str(exc)
        assert "slug collision" in str(exc)
