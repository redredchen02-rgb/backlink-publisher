"""optimization subpackage — Closed-loop backlink-publishing optimization (Plan 2026-06-05-001).

Public API:
    - ``OptimizationState`` — read/write ``optimization_state.json``
    - ``CanaryDriftRule``, ``RecheckSurvivalRule`` — weight-adjustment rules
    - ``collect_signals`` — gather publishing outcome signals from existing gates
    - ``run_rules`` — apply rules engine to compute new dispatch weights
"""

from __future__ import annotations

from .models import RuleResult
from .state import OptimizationState

__all__ = [
    "OptimizationState",
    "RuleResult",
]
