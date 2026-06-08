"""R8 — keepalive WebUI cycle panel (plan 2026-06-08-001).

Covers:
  - build_cycle_status_view() unit tests (service layer, injectable state)
  - GET /ce:keep-alive/cycle-status route (200, JSON shape)
  - POST /ce:keep-alive/reset-exhausted route (origin guard, was_present)
  - MAX_RETRY=0 clamp (R1 downstream fix)
  - 403 origin-guard returns JSON (R3 downstream fix)
  - keepalive-reset-exhausted CLI (R4 downstream fix)
"""
from __future__ import annotations

__tier__ = "integration"

import json
from unittest.mock import patch

import pytest

import webui
from backlink_publisher.cli.keepalive_reset_exhausted import main as reset_cli_main
from backlink_publisher.keepalive.run_state import KeepaliveRunState
from backlink_publisher.optimization.state import OptimizationState
from webui_app.services.keep_alive import build_cycle_status_view

_PORT = 8888
_GOOD_ORIGIN = {"Origin": f"http://127.0.0.1:{_PORT}"}

_NOW = "2026-06-08T06:30:00+00:00"


# ── helpers ───────────────────────────────────────────────────────────────────


def _rs_with_data(tmp_path, *, last_run_at=_NOW, cycle_summary=None, retry_counts=None):
    rs = KeepaliveRunState(data_dir=tmp_path)
    state = {
        "version": 1,
        "last_run_at": last_run_at,
        "last_cycle_summary": cycle_summary or {
            "gaps_found": 3,
            "published": 2,
            "reverified_alive": 5,
            "reverified_dead": 1,
            "exhausted_skipped": 1,
        },
        "retry_counts": retry_counts or {},
    }
    rs.save(state)
    return rs


def _os_with_platforms(tmp_path, platforms: dict):
    """platforms: {name: {current, locked, stats?}}"""
    from backlink_publisher.optimization.models import default_state
    os_inst = OptimizationState(data_dir=tmp_path)
    state = default_state()
    for name, p in platforms.items():
        state["weights"][name] = {
            "base": 1.0,
            "current": p.get("current", 1.0),
            "locked": p.get("locked", False),
            "adjustments": [],
        }
        if "stats" in p:
            state["stats"][name] = p["stats"]
    os_inst.save(state)
    return os_inst


# ── TestBuildCycleStatusView ──────────────────────────────────────────────────


class TestBuildCycleStatusView:
    def test_empty_state_returns_has_data_false(self, tmp_path):
        rs = KeepaliveRunState(data_dir=tmp_path)
        os_inst = OptimizationState(data_dir=tmp_path)
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        assert result["has_data"] is False
        assert result["last_run_at"] is None
        assert result["exhausted"] == []
        assert result["exhausted_total"] == 0

    def test_with_run_data_returns_has_data_true(self, tmp_path):
        rs = _rs_with_data(tmp_path)
        os_inst = OptimizationState(data_dir=tmp_path)
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        assert result["has_data"] is True
        assert result["last_run_at"] == _NOW

    def test_cycle_summary_forwarded(self, tmp_path):
        rs = _rs_with_data(tmp_path, cycle_summary={"gaps_found": 7, "published": 4})
        os_inst = OptimizationState(data_dir=tmp_path)
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        assert result["cycle_summary"]["gaps_found"] == 7
        assert result["cycle_summary"]["published"] == 4

    def test_exhausted_list_only_includes_at_max_retry(self, tmp_path):
        retry_counts = {
            "https://ok.example.com/": {"attempts": 1, "last_attempt_at": None,
                                        "last_outcome": "alive"},
            "https://ex.example.com/a": {"attempts": 3, "last_attempt_at": "2026-06-07T10:00:00",
                                         "last_outcome": "link_stripped"},
        }
        rs = _rs_with_data(tmp_path, retry_counts=retry_counts)
        os_inst = OptimizationState(data_dir=tmp_path)
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        # MAX_RETRY default is 3 — only the second entry qualifies.
        assert result["exhausted_total"] == 1
        assert len(result["exhausted"]) == 1
        assert result["exhausted"][0]["target_url"] == "https://ex.example.com/a"
        assert result["exhausted"][0]["attempts"] == 3

    def test_exhausted_sorted_by_last_attempt_desc(self, tmp_path):
        retry_counts = {
            "https://a.example.com/": {"attempts": 3, "last_attempt_at": "2026-06-05T00:00:00",
                                       "last_outcome": "err"},
            "https://b.example.com/": {"attempts": 3, "last_attempt_at": "2026-06-07T00:00:00",
                                       "last_outcome": "err"},
            "https://c.example.com/": {"attempts": 3, "last_attempt_at": None,
                                       "last_outcome": "err"},
        }
        rs = _rs_with_data(tmp_path, retry_counts=retry_counts)
        result = build_cycle_status_view(run_state=rs)
        urls = [e["target_url"] for e in result["exhausted"]]
        # b (2026-06-07) > a (2026-06-05) > c (None sorts last via "" coercion)
        assert urls.index("https://b.example.com/") < urls.index("https://a.example.com/")
        assert urls.index("https://a.example.com/") < urls.index("https://c.example.com/")

    def test_exhausted_truncated_at_20(self, tmp_path):
        retry_counts = {
            f"https://t{i}.example.com/": {"attempts": 3, "last_attempt_at": None,
                                           "last_outcome": "err"}
            for i in range(25)
        }
        rs = _rs_with_data(tmp_path, retry_counts=retry_counts)
        result = build_cycle_status_view(run_state=rs)
        assert result["exhausted_total"] == 25
        assert len(result["exhausted"]) == 20

    def test_platform_health_from_opt_state(self, tmp_path):
        rs = _rs_with_data(tmp_path)
        os_inst = _os_with_platforms(tmp_path, {
            "blogger": {"current": 1.2, "locked": False,
                        "stats": {"alive_count": 8, "total_published": 12}},
        })
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        assert len(result["platforms"]) == 1
        p = result["platforms"][0]
        assert p["name"] == "blogger"
        assert abs(p["weight"] - 1.2) < 1e-3
        assert p["circuit_broken"] is False
        assert p["locked"] is False
        assert p["alive_count"] == 8
        assert p["total_published"] == 12

    def test_circuit_broken_when_weight_zero_and_not_locked(self, tmp_path):
        rs = _rs_with_data(tmp_path)
        os_inst = _os_with_platforms(tmp_path, {
            "telegraph": {"current": 0.0, "locked": False},
        })
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        p = result["platforms"][0]
        assert p["circuit_broken"] is True
        assert p["locked"] is False

    def test_locked_platform_not_circuit_broken(self, tmp_path):
        rs = _rs_with_data(tmp_path)
        os_inst = _os_with_platforms(tmp_path, {
            "telegraph": {"current": 0.5, "locked": True},
        })
        result = build_cycle_status_view(run_state=rs, opt_state=os_inst)
        p = result["platforms"][0]
        assert p["locked"] is True
        assert p["circuit_broken"] is False

    def test_opt_state_failure_returns_empty_platforms(self, tmp_path):
        rs = _rs_with_data(tmp_path)

        class _BrokenOpt:
            def to_summary(self):
                raise RuntimeError("disk error")

        result = build_cycle_status_view(run_state=rs, opt_state=_BrokenOpt())
        assert result["platforms"] == []
        assert result["has_data"] is True


# ── TestCycleStatusRoutes ─────────────────────────────────────────────────────


@pytest.fixture
def client(disable_csrf):
    return webui.app.test_client()


class TestCycleStatusRoutes:
    def test_get_cycle_status_returns_200_with_has_data_key(self, client):
        with patch("webui_app.services.keep_alive.build_cycle_status_view") as mock_view:
            mock_view.return_value = {
                "has_data": False,
                "last_run_at": None,
                "cycle_summary": {},
                "platforms": [],
                "exhausted": [],
                "exhausted_total": 0,
            }
            resp = client.get("/ce:keep-alive/cycle-status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "has_data" in body

    def test_get_cycle_status_with_live_data_returns_200(self, client):
        resp = client.get("/ce:keep-alive/cycle-status")
        assert resp.status_code == 200
        body = resp.get_json()
        assert "has_data" in body
        assert "exhausted" in body
        assert "platforms" in body

    def test_reset_exhausted_missing_target_url_returns_400(self, client):
        resp = client.post(
            "/ce:keep-alive/reset-exhausted",
            json={},
            headers=_GOOD_ORIGIN,
        )
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"

    def test_reset_exhausted_missing_origin_returns_403(self, client):
        resp = client.post(
            "/ce:keep-alive/reset-exhausted",
            json={"target_url": "https://example.com/"},
        )
        assert resp.status_code == 403

    def test_reset_exhausted_absent_url_returns_was_present_false(self, client):
        resp = client.post(
            "/ce:keep-alive/reset-exhausted",
            json={"target_url": "https://notinthere.example.com/"},
            headers=_GOOD_ORIGIN,
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["was_present"] is False

    def test_reset_exhausted_present_url_returns_was_present_true(
        self, client, tmp_path, monkeypatch
    ):
        target = "https://51acgs.com/comic/117"
        rs = KeepaliveRunState(data_dir=tmp_path)
        state = {
            "version": 1,
            "last_run_at": _NOW,
            "last_cycle_summary": {},
            "retry_counts": {
                target: {"attempts": 3, "last_attempt_at": None, "last_outcome": "err"}
            },
        }
        rs.save(state)

        with patch(
            "backlink_publisher.keepalive.run_state.KeepaliveRunState",
            return_value=rs,
        ):
            resp = client.post(
                "/ce:keep-alive/reset-exhausted",
                json={"target_url": target},
                headers=_GOOD_ORIGIN,
            )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["was_present"] is True
        # Confirm reset actually removed the entry.
        assert target not in rs.load().get("retry_counts", {})


# ── R1: MAX_RETRY clamp ───────────────────────────────────────────────────────


class TestMaxRetryClamp:
    def test_max_retry_zero_clamps_to_one(self, monkeypatch):
        monkeypatch.setenv("KEEPALIVE_MAX_RETRY", "0")
        rs = KeepaliveRunState()
        assert rs.MAX_RETRY == 1

    def test_max_retry_negative_clamps_to_one(self, monkeypatch):
        monkeypatch.setenv("KEEPALIVE_MAX_RETRY", "-5")
        rs = KeepaliveRunState()
        assert rs.MAX_RETRY == 1

    def test_max_retry_positive_unchanged(self, monkeypatch):
        monkeypatch.setenv("KEEPALIVE_MAX_RETRY", "5")
        rs = KeepaliveRunState()
        assert rs.MAX_RETRY == 5

    def test_max_retry_zero_does_not_exhaust_all_targets(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KEEPALIVE_MAX_RETRY", "0")
        retry_counts = {
            "https://example.com/": {"attempts": 0, "last_attempt_at": None,
                                     "last_outcome": None},
        }
        rs = _rs_with_data(tmp_path, retry_counts=retry_counts)
        result = build_cycle_status_view(run_state=rs)
        # With MAX_RETRY clamped to 1, attempts=0 < 1 → not exhausted.
        assert result["exhausted_total"] == 0


# ── R3: 403 returns JSON ──────────────────────────────────────────────────────


class TestOriginGuard403Json:
    def test_missing_origin_returns_json_not_html(self, client):
        resp = client.post(
            "/ce:keep-alive/reset-exhausted",
            json={"target_url": "https://example.com/"},
        )
        assert resp.status_code == 403
        body = resp.get_json()
        assert body is not None, "403 response should be JSON, not HTML"
        assert body.get("status") == "error"

    def test_403_content_type_is_json(self, client):
        resp = client.post(
            "/ce:keep-alive/reset-exhausted",
            json={"target_url": "https://example.com/"},
        )
        assert resp.status_code == 403
        assert "application/json" in resp.content_type


# ── R4: keepalive-reset-exhausted CLI ────────────────────────────────────────


class TestKeepaliveResetExhaustedCli:
    def test_cli_removes_present_url(self, tmp_path, monkeypatch, capsys):
        target = "https://51acgs.com/comic/117"
        rs = KeepaliveRunState(data_dir=tmp_path)
        state = {
            "version": 1,
            "last_run_at": _NOW,
            "last_cycle_summary": {},
            "retry_counts": {
                target: {"attempts": 3, "last_attempt_at": None, "last_outcome": "err"}
            },
        }
        rs.save(state)

        with patch(
            "backlink_publisher.keepalive.run_state.KeepaliveRunState",
            return_value=rs,
        ):
            reset_cli_main([target])

        assert target not in rs.load().get("retry_counts", {})

    def test_cli_json_output_was_present_true(self, tmp_path, monkeypatch, capsys):
        target = "https://51acgs.com/comic/118"
        rs = KeepaliveRunState(data_dir=tmp_path)
        state = {
            "version": 1,
            "last_run_at": _NOW,
            "last_cycle_summary": {},
            "retry_counts": {
                target: {"attempts": 3, "last_attempt_at": None, "last_outcome": "err"}
            },
        }
        rs.save(state)

        with patch(
            "backlink_publisher.keepalive.run_state.KeepaliveRunState",
            return_value=rs,
        ):
            reset_cli_main([target, "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "ok"
        assert out["was_present"] is True

    def test_cli_absent_url_json_was_present_false(self, tmp_path, capsys):
        rs = KeepaliveRunState(data_dir=tmp_path)
        rs.save({"version": 1, "last_run_at": None, "last_cycle_summary": {},
                 "retry_counts": {}})

        with patch(
            "backlink_publisher.keepalive.run_state.KeepaliveRunState",
            return_value=rs,
        ):
            reset_cli_main(["https://nothere.example.com/", "--json"])

        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "ok"
        assert out["was_present"] is False
