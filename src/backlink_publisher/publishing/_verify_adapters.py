"""Facade: re-exports all verify symbols for backward compatibility.

Wave 3 Unit 3 (2026-06-11): implementation split into:
  - ``_verify_setup.py``       — offline setup checks + ``verify_adapter_setup``
  - ``_verify_live_probes.py`` — live probe impls + result helpers

External callers (``adapters/__init__.py``, tests) continue to import from
this module without changes.
"""

from ._verify_live_probes import (  # noqa: F401
    _BLOGGER_USERS_SELF,
    _BLOGGER_VERIFY_TIMEOUT_S,
    _GHPAGES_VERIFY_TIMEOUT_S,
    _network_error,
    _never,
    _non_json,
    _ok_result,
    _timeout_result,
    _token_expired,
    _utc_now_iso,
    _VELOG_CURRENT_USER_QUERY,
    _VELOG_VERIFY_TIMEOUT_S,
    _verify_blogger_live,
    _verify_ghpages_live,
    _verify_live,
    _verify_telegraph_live,
    _verify_velog_live,
)
from ._verify_setup import (  # noqa: F401
    _check_ghpages_setup,
    _check_medium_setup,
    _check_telegraph_setup,
    _check_velog_setup,
    _SETUP_CHECKS,
    _verify_dry_run,
    verify_adapter_setup,
)
