"""Cross-adapter contract: retryable HTTP statuses must route through TransientError.

Audit finding [06]: 16 API adapters raised ``ExternalServiceError`` inside their
``fn()`` for a retryable status (429). ``retry_transient_call`` short-circuits
``ExternalServiceError``/``DependencyError`` and re-raises BEFORE consulting the
``is_retryable`` predicate (a load-bearing, separately-tested contract — see
``tests/test_adapter_retry.py::test_external_service_error_passes_through_immediately``).
So every one of those adapters' ``is_retryable=lambda exc: isinstance(exc,
ExternalServiceError) and any(f"HTTP {code}" in str(exc) ...)`` predicate was dead
code and 429s never retried/backed off.

The correct pattern (blogger_api / medium_api / velog_graphql): raise
``TransientError(status_code)`` for retryable statuses (a non-ExternalServiceError
type that falls through to the backoff path), gate retry on
``isinstance(exc, TransientError)``, and convert an exhausted ``TransientError``
back to ``ExternalServiceError`` at the call site.

This structural guard locks the invariant across all 16 so the whole bug class
cannot silently regress. A behavioural proof that the retry actually fires lives
in ``tests/test_adapter_hatena_atompub.py::test_publish_retries_on_429_then_succeeds``.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

import pytest

_ADAPTERS_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "backlink_publisher" / "publishing" / "adapters"
)

# The 16 adapters that carried the dead predicate (grep of the retired signature).
_ADAPTERS = [
    "devto_api",
    "ghpages",
    "gitlabpages",
    "hackmd_api",
    "hashnode_graphql",
    "hatena_atompub",
    "linkedin_api",
    "mataroa_api",
    "notion_api",
    "qiita_api",
    "rentry_api",
    "substack_api",
    "tumblr_api",
    "wordpresscom_api",
    "writeas_api",
    "zenn_github",
]

_DEAD_PREDICATE = 'f"HTTP {code}" in str(exc)'


@pytest.mark.parametrize("module_name", _ADAPTERS)
def test_adapter_does_not_use_dead_external_service_error_retry_predicate(
    module_name: str,
) -> None:
    src = (_ADAPTERS_DIR / f"{module_name}.py").read_text(encoding="utf-8")
    assert _DEAD_PREDICATE not in src, (
        f"{module_name}: dead is_retryable predicate — ExternalServiceError raised "
        "inside fn() short-circuits retry_transient_call before is_retryable runs, "
        "so 429 never retries. Raise TransientError(status) for retryable statuses "
        "and gate retry on isinstance(exc, TransientError)."
    )


@pytest.mark.parametrize("module_name", _ADAPTERS)
def test_adapter_raises_transient_error_for_retryable_status(
    module_name: str,
) -> None:
    src = (_ADAPTERS_DIR / f"{module_name}.py").read_text(encoding="utf-8")
    assert "TransientError" in src, (
        f"{module_name}: must import/raise TransientError so a retryable HTTP "
        "status reaches retry_transient_call's backoff path."
    )
    assert "isinstance(exc, TransientError)" in src, (
        f"{module_name}: is_retryable must gate on isinstance(exc, TransientError) "
        "(the type that survives the ExternalServiceError short-circuit)."
    )
