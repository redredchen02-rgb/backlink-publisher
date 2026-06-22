"""BindAPI — stateful channel browser-bind flow, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings security increment). The four
bind operations and their security-critical logic were **moved here, not copied**,
from ``routes/bind.py``:

  * ``start``         — refuse a fresh bind while an identity_mismatch is
                        unresolved (the PR #83 TOCTOU guard, 409), else launch the
                        browser-login job.
  * ``poll``          — return the job snapshot (channel-scoped 404).
  * ``resolve_keep``  — operator keeps the previously bound account. The atomic
                        ``_restore`` closure either restores ``bound`` or, if the
                        stored credential vanished, demotes to ``expired`` — NEVER
                        the destructive ``replace`` path (the bug PR #83 flagged).
  * ``resolve_replace`` — operator accepts the new account: wipe storage-state +
                        last-account artifacts, drop to unbound. No half-bound state.

A single source of this logic now backs both the legacy
``/settings/channels/<channel>/...`` HTML routes (redirect / jsonify) and the new
``/api/v1/settings/channels/<channel>/bind*`` JSON bindings (problem+json). Copying
it would have risked the keep/replace divergence or the TOCTOU window drifting on
one transport only.

This module performs NO transport concerns — it never reads ``flask.request`` and
never aborts; the loopback / Origin / ALLOW_NETWORK guards stay at the HTTP
boundary in each binding. Channel-allow-list validation (anti-traversal) IS here,
so neither transport can forget it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backlink_publisher._util.errors import UsageError
from backlink_publisher.cli._bind.channels import CHANNELS
from backlink_publisher.config.loader import _config_dir

from ..services.bind_job import registry as _bind_registry


@dataclass(frozen=True)
class BindResult:
    """Transport-neutral outcome of a bind operation.

    On success ``error_class`` is ``None`` and ``payload`` carries the JSON body.
    On failure ``error_class`` selects the ``/api/v1`` problem type and ``error``
    is the machine code the legacy ``{"status":"error", ...}`` envelope uses;
    ``status`` is the HTTP status both transports apply.
    """

    payload: dict | None = None
    status: int = 200
    error: str | None = None
    message: str = ""
    error_class: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_class is None


def _bad_channel() -> BindResult:
    # Distinct error_class so the legacy route renders abort(400) (anti-traversal,
    # NOT a JSON envelope) while a same-status UsageError renders the JSON envelope.
    return BindResult(status=400, error="unknown_channel", message="未知渠道",
                      error_class="bad_channel")


class BindAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def start(self, channel: str) -> BindResult:
        if channel not in CHANNELS:
            return _bad_channel()

        # PR #83 adversarial review: refuse to start a fresh bind while the
        # channel is in ``identity_mismatch``. Letting the bind run in parallel
        # with an open keep/replace decision creates a TOCTOU window where the
        # resolution route can race the new bind's ``mark_bound`` and silently
        # accept the new account under the guise of "keep old".
        from webui_store.channel_status import get_status

        if get_status(channel).get("status") == "identity_mismatch":
            return BindResult(
                status=409, error="identity_mismatch_unresolved",
                message="请先在设置页选择保留旧账号或替换为新账号，再发起新的绑定。",
                error_class="conflict",
            )

        try:
            job = _bind_registry.start(channel)
        except UsageError as exc:
            return BindResult(status=400, error=str(exc), error_class="invalid_request")
        return BindResult(payload={"job_id": job.id, "channel": channel, "status": "running"})

    def poll(self, channel: str, job_id: str) -> BindResult:
        if channel not in CHANNELS:
            return _bad_channel()
        snapshot = _bind_registry.poll(job_id)
        if snapshot is None or snapshot.get("channel") != channel:
            return BindResult(status=404, error="not_found", message="绑定任务不存在",
                              error_class="not_found")
        return BindResult(payload=snapshot)

    def resolve_keep(self, channel: str) -> BindResult:
        """Operator keeps the previously bound account. Flip status back to bound;
        storage_state.json and last_account.txt are unchanged (the driver never
        persisted the mismatched session, so the old state on disk is still valid).

        Returns ``{"resolved": "kept" | "expired" | "noop"}``.
        """
        if channel not in CHANNELS:
            return _bad_channel()

        from webui_store import channel_status_store

        # PR #83 adversarial review: the precondition check + the resolution write
        # MUST be one atomic step. A get_status() → if-check → update() shape had a
        # TOCTOU window where a concurrent bind subprocess could complete between
        # the check and the closure, causing the closure to read a freshly-bound
        # (different account!) record and write status=bound for the WRONG account
        # under the operator's "keep old" click. Moving the check inside the
        # closure means we either restore the same identity_mismatch record we
        # observed or no-op cleanly.
        outcome = {"resolved": "noop"}

        def _restore(current_state: dict) -> dict:
            current_state = dict(current_state)
            existing = current_state.get(channel, {})
            if existing.get("status") != "identity_mismatch":
                # State changed under us (concurrent resolution / bind completion).
                # No-op so we don't silently accept whatever the other writer landed.
                outcome["resolved"] = "noop"
                return current_state
            storage_state_path = existing.get("storage_state_path")
            if not storage_state_path or not Path(storage_state_path).exists():
                # Old credential is gone (external wipe or never persisted). Demote
                # to expired — semantically honest: "you used to be bound, the
                # credential is no longer on disk, please rebind". Crucially NOT
                # "replace" (which would also delete sibling last-account files);
                # the UI label says "keep", and silent destructive escalation is the
                # bug the reviewer flagged.
                outcome["resolved"] = "expired"
                current_state[channel] = {
                    "status": "expired",
                    "bound_at": existing.get("bound_at"),
                    "storage_state_path": existing.get("storage_state_path"),
                    "last_verified_at": None,
                }
                return current_state
            # Happy path: restore bound with the original bound_at (don't pretend it
            # just happened); clear identity_mismatch_* sentinels and
            # last_verified_at (probe must re-confirm).
            outcome["resolved"] = "kept"
            current_state[channel] = {
                "status": "bound",
                "bound_at": existing.get("bound_at"),
                "storage_state_path": existing.get("storage_state_path"),
                "last_verified_at": None,
            }
            return current_state

        channel_status_store.update(_restore)
        return BindResult(payload=outcome)

    def resolve_replace(self, channel: str) -> BindResult:
        """Operator accepts the new account: wipe storage_state.json +
        last_account.txt and flip status to unbound — operator must re-bind to
        capture the new account cleanly (no half-bound state).

        Returns ``{"resolved": "replaced"}``.
        """
        if channel not in CHANNELS:
            return _bad_channel()
        _execute_replace(channel)
        return BindResult(payload={"resolved": "replaced"})


def _execute_replace(channel: str) -> None:
    """Delete storage_state.json + last-account artifacts; reset to unbound.
    Shared helper between identity-mismatch/replace and the defensive fallback in
    identity-mismatch/keep."""
    from webui_store import channel_status_store

    cfg = _config_dir()
    for fname in (
        f"{channel}-storage-state.json",
        f"{channel}-last-account.txt",
        f"{channel}-last-account.tentative",
    ):
        p = cfg / fname
        if p.exists():
            try:
                p.unlink()
            except OSError:
                # Best-effort delete; if a stale file remains, the next bind
                # overwrites it. Don't fail the route.
                pass

    def _wipe(current_state: dict) -> dict:
        current_state = dict(current_state)
        current_state.pop(channel, None)
        return current_state

    channel_status_store.update(_wipe)
