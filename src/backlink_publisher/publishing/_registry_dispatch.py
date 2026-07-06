"""Table-driven publish dispatcher — extracted from registry.py.

The single ``dispatch()`` function walks a platform's registered adapter
chain, trying each entry in order (class or instance). DependencyError
entries fall through to the next; ExternalServiceError propagates
immediately; AuthExpiredError propagates so the WebUI can prompt re-bind.

See ``registry.py`` for the full module docstring (ABC, fallback semantics,
throttle metadata, etc.).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from backlink_publisher._util.errors import (
    AuthExpiredError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.config import Config

from .registry import _REGISTRY

if TYPE_CHECKING:
    from .adapters.base import AdapterResult
    from .registry import Publisher


def _emit_degraded(platform: str, *, failed_adapter: str, to_adapter: str) -> None:
    """Emit a degraded ``publish_attempt`` event when a transient triggers a
    same-account fallback (Plan 2026-06-15-001 A3, observe-only).

    Never raises and carries no URL/body — operators see *that* a primary adapter
    degraded and to which fallback, without per-adapter circuit accounting (the
    breaker stays per-platform; option A).
    """
    try:
        from .reliability.events import emit_attempt, Outcome

        emit_attempt(
            platform,
            Outcome.TRANSIENT,
            0.0,
            error_class="ExternalServiceError",
            degraded=True,
            failed_adapter=failed_adapter,
            to_adapter=to_adapter,
        )
    except Exception:
        pass


def dispatch(
    payload: dict[str, Any],
    mode: str,
    config: Config,
    dry_run: bool = False,
    *,
    banner_emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> AdapterResult:
    """Walk the registered fallback chain for ``payload["platform"]``.

    Error semantics: dry-run returns a sentinel result;
    ``AuthExpiredError`` (subclass of ``DependencyError``) propagates
    immediately so operator UX can prompt re-bind (Plan
    2026-05-20-016 Unit 0b); plain ``DependencyError`` from one
    adapter falls through to the next; ``ExternalServiceError``
    propagates; unknown platform raises ``ExternalServiceError``.

    Banner embed (Plan 2026-05-20-004 Unit 1): when ``banner_emit`` is
    supplied AND the payload carries a non-degraded ``banner`` field
    (``banner["path"]`` not None), each available adapter in the chain
    gets a chance to embed via ``adapter.embed_banner`` before its
    ``publish()`` runs.  See ``banner_dispatcher.apply`` for the
    branch semantics.  ``banner_emit`` is the event sink (kind,
    payload) and defaults to ``None`` which suppresses banner work
    entirely (back-compat for callers that don't set up banners).
    """
    from .adapters.base import AdapterResult  # local: breaks module-level circular

    plat = payload.get("platform", "")

    if dry_run:
        return AdapterResult(
            status="draft",
            adapter=f"{plat}-api",
            platform=plat,
            _dry_run=True,
            _command=f"publish to {plat} --mode {mode} (dry-run)",
        )

    _entry = _REGISTRY.get(plat)
    if not _entry:
        raise ExternalServiceError(f"unsupported platform: {plat}")
    chain = _entry.publishers

    banner_dict = payload.get("banner") if banner_emit is not None else None
    do_banner = banner_dict is not None and banner_dict.get("path") is not None
    strict = bool(do_banner and config.image_gen and config.image_gen.strict)

    # Local import: reliability imports adapters, so importing transient_policy
    # at module level would re-enter this package mid-init.
    from .reliability.transient_policy import classify_transient, TransientDecision

    last_dep_error: DependencyError | None = None
    # A prior adapter's transient error, awaiting a fall-or-raise decision against
    # the NEXT available adapter (Plan 2026-06-15-001 A1). Tuple of
    # ``(exc, failed_adapter_name, failed_mechanism)``.
    pending_transient: tuple[ExternalServiceError, str, str] | None = None

    for entry in chain:
        # Entry may be a Publisher subclass (legacy) or instance
        # (BrowserPublishDispatcher.for_channel — Plan 2026-05-21-001 U2).
        is_class = isinstance(entry, type)
        publisher_cls: type[Publisher] = entry if is_class else type(entry)  # type: ignore[assignment]

        this_name = publisher_cls.__name__
        this_mech = getattr(publisher_cls, "mechanism", "api")

        # A1: if a prior adapter raised a transient, decide fall-or-raise BEFORE
        # evaluating this candidate. A FAIL_FAST raises immediately and never
        # touches this adapter's ``available()`` — preserving the legacy contract
        # that an ExternalServiceError terminates the chain without probing
        # further adapters (their ``available()`` may be slow or side-effecting).
        if pending_transient is not None:
            t_exc, t_name, t_mech = pending_transient
            decision = classify_transient(
                t_exc,
                platform=plat,
                transition=(t_name, this_name),
                same_mechanism=(t_mech == this_mech),
            )
            if decision is TransientDecision.FAIL_FAST:
                raise t_exc
            # FALLBACK_SAFE: try this candidate. If unavailable, the pending
            # transient carries to the next entry's gate.

        if not publisher_cls.available(config):
            continue

        if pending_transient is not None:
            _emit_degraded(
                plat, failed_adapter=pending_transient[1], to_adapter=this_name
            )
            pending_transient = None

        try:
            adapter: Publisher = entry() if is_class else entry  # type: ignore[operator,assignment]
            if do_banner:
                # Lazy import avoids a top-level cycle (banner_dispatcher
                # lives in the same publishing package and is leaf-level,
                # but importing it during registry init is unnecessary
                # for the >99% of dispatch calls that have no banner).
                from . import banner_dispatcher

                new_body = banner_dispatcher.apply(
                    adapter,
                    banner=banner_dict,
                    body=payload.get("content_markdown", ""),
                    platform=plat,
                    strict=strict,
                    emit=banner_emit,  # type: ignore[arg-type]  # do_banner gates non-None
                )
                if new_body != payload.get("content_markdown"):
                    payload = {**payload, "content_markdown": new_body}
            return adapter.publish(payload, mode, config)
        except AuthExpiredError:
            # Plan 2026-05-20-016 Unit 0b: credentials were valid enough to
            # reach the adapter but have expired — operator must re-bind.
            # Falling through would silently try the next chain entry and
            # hide the expiry; the correct semantics is to propagate so
            # the webui can surface "请重新绑定 <channel>" UX.
            # Order matters: AuthExpiredError IS-A DependencyError (per
            # _util/errors.py), so this except MUST precede the
            # DependencyError catch below — Python catches the first
            # matching except clause.
            raise
        except DependencyError as e:
            # Adapter declared itself missing a prerequisite → try next.
            last_dep_error = e
            continue
        except ExternalServiceError as e:
            # A1: defer the fall/raise decision to the next available adapter's
            # gate above. With no whitelisted fallback this raises at loop-end —
            # preserving the legacy "ExternalServiceError propagates" contract.
            pending_transient = (e, this_name, this_mech)
            continue

    # A pending transient with no safe fallback target left → surface it
    # (identical outcome to the legacy immediate-propagate path).
    if pending_transient is not None:
        raise pending_transient[0]
    if last_dep_error is not None:
        raise last_dep_error
    raise DependencyError(
        f"No available adapter for platform {plat!r} — every entry in the "
        f"chain returned available()=False."
    )
