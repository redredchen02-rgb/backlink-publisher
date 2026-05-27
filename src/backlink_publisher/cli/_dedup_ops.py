"""Operator dedup escape verbs for publish-backlinks (U5a, extended in U5b).

Early-exit verbs (``--forget``, ``--list-uncertain``, and later
``--adjudicate-uncertain``) that read/mutate the authoritative dedup store and
its append-only audit log. Mutual exclusion with the publish/checkpoint verbs is
enforced in :func:`_publish_helpers._handle_checkpoint_ops`; this module performs
the action and exits 0.

Extracted from ``_publish_helpers.py`` to keep that file under the monolith
budget and to give the dedup verbs (which grow with U5b) their own home.

Plan: docs/plans/2026-05-27-005-feat-cross-run-publish-idempotency-plan.md (U5a).
"""

from __future__ import annotations

import sys
from typing import Any


def _handle_dedup_ops(args: Any) -> None:
    """Dispatch the dedup escape verbs. Each raises ``SystemExit(0)`` on success
    (or exits 1 via ``emit_error`` on a usage error). No stdin needed."""
    if getattr(args, "forget", None):
        _do_forget(args)
        raise SystemExit(0)

    if getattr(args, "list_uncertain", False):
        _do_list_uncertain(args)
        raise SystemExit(0)


def _do_forget(args: Any) -> None:
    """Clear one dedup key → ``absent`` and append an audit entry. Single key
    only: a glob/wildcard in either field is rejected (exit 1) so a wrong pattern
    cannot silently mass-retire backlinks."""
    from backlink_publisher._util.errors import emit_error
    from backlink_publisher.idempotency import DedupKey, DedupStore
    from backlink_publisher.idempotency import audit_log

    platform, target_url = args.forget
    if not args.reason:
        emit_error("error: --forget requires --reason <text>", exit_code=1)
    if any("*" in v or "?" in v for v in (platform, target_url)):
        emit_error(
            "error: --forget takes a single concrete key; globs/wildcards are "
            "rejected (forget one key at a time)",
            exit_code=1,
        )

    key = DedupKey(platform=platform, target_url=target_url)
    store = DedupStore()
    record = store.get(key)
    from_state = record.state if record is not None else None

    # Append the audit entry BEFORE deleting so a crash mid-forget still leaves a
    # trail (the row simply remains; the operator re-runs). Canonical target_url
    # (key.target_url) is logged so U6's touched-key check matches the store key.
    audit_log.append_entry(
        action="forget",
        platform=key.platform,
        target_url=key.target_url,
        account=key.account,
        from_state=from_state,
        to_state="absent",
        reason=args.reason,
        run_id=getattr(args, "resume", None),
    )
    store.forget(key)
    if from_state is None:
        print(
            f"forget: key was already absent (platform={key.platform}); "
            "audit entry recorded.",
            file=sys.stderr,
        )
    else:
        print(
            f"forget: cleared {key.platform} key (was {from_state}); now "
            "re-publishable.",
            file=sys.stderr,
        )


def _do_list_uncertain(args: Any) -> None:
    """Print held (``uncertain``) dedup rows on stdout (the operator needs the
    target_url to adjudicate). Optional ``--platform`` filter."""
    from backlink_publisher.idempotency import DedupStore

    platform_filter = getattr(args, "platform", None)
    rows = DedupStore().list_by_state("uncertain", platform=platform_filter)
    if not rows:
        print("No uncertain (held) dedup rows.")
        return
    print(f"{'PLATFORM':<14}  {'STATE':<10}  {'RUN_ID':<28}  TARGET_URL")
    print("-" * 90)
    for r in rows:
        print(
            f"{r.platform:<14}  {r.state:<10}  {(r.run_id or ''):<28}  {r.target_url}"
        )
