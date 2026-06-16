---
date: 2026-05-28
topic: deterministic-planning-purity
---

# Deterministic Planning ↔ Non-Deterministic Execution Separation

## Summary

Formalize backlink-publisher's implicit architecture into a documented principle: **planning is deterministic and testable; publishing depends on external platform state.** The principle applies at the pipeline-command level (`plan-backlinks` / `validate-backlinks` / `publish-backlinks`), with explicit callouts for non-deterministic dependencies (content_fetch, LLM calls, image gen) that feed the planning step as external inputs.

---

## Problem Frame

The current pipeline has always operated with an implicit separation of concerns — `plan-backlinks` generates articles from seeds, `validate-backlinks` checks them, and `publish-backlinks` sends them to external platforms. But this principle has never been documented, causing three concrete problems:

**Scope creep.** During development, there is no written contract preventing new features from adding network calls or I/O to planning steps. Each "small" addition erodes the determinism of the planning stage gradually. Without a documented boundary, every feature PR needs an independent judgment call about where functionality belongs.

**Testing gaps.** Tests for planning code must mock non-deterministic dependencies (content_fetch, LLM, image gen), but the boundary of what needs mocking is undocumented. Engineers must infer from existing test fixtures what to mock — leading to either under-mocked tests that fail intermittently, or over-mocked tests that lose coverage.

**Onboarding friction.** New contributors must infer the architecture from reading source files rather than consulting a principle document. The `validate/engine.py` purity contract is explicitly annotated, but `plan_backlinks/_engine.py` has no equivalent, leaving ambiguity about whether it should.

The pipeline's output contract (stdout = clean JSONL, stderr = diagnostics, exit 0 on success) is already well-defined. What's missing is the *process contract* — which steps are pure computation, which are I/O-bound, and where the line is.

---

## Requirements

**[Pipeline-Command Boundary]**

- R1. The document MUST define each pipeline command's nature (deterministic or non-deterministic) in a comparison table, with explicit rationale for each classification.
- R2. `plan-backlinks` MUST be classified as **deterministic with non-deterministic inputs**. Its engine (link building, template filling, payload assembly) is pure computation; `content_fetch`, LLM calls, and image generation are external inputs that feed the engine before it runs.
- R3. `validate-backlinks` MUST be classified as **deterministic (pure engine)**. Its engine is already annotated PURE. The optional `--no-validate-url-check` flag gates URL reachability probes (the only non-deterministic path) — the pure engine is the contract; URL probes are a pre-flight.
- R4. `publish-backlinks` MUST be classified as **non-deterministic**. Platform API calls, auth state, rate limits, and network failures are inherently non-deterministic. The policy layer (circuit breaker, health gate, retry, dedup) exists to manage this non-determinism, not to eliminate it.

**[Non-Deterministic Dependency Callouts]**

- R5. The document MUST explicitly list non-deterministic dependencies that feed deterministic planning steps, with the rationale that they are **external inputs** to the pure kernel, not part of planning computation:
  - `content.fetch` — network I/O for seed content retrieval
  - LLM API calls — anchor text generation (non-deterministic by nature)
  - Image generation API — banner artwork generation (network I/O)
  - `linkcheck.http` — URL reachability checks (network I/O, when used in validate context)

**[Exceptions and Edge Cases]**

- R6. The document MUST address validate-backlinks' dual nature: pure engine is the contract; `--no-validate-url-check` is an optional non-deterministic pre-flight that can be skipped. The pure path is the default.
- R7. The document MUST confirm that read-only standalone commands (`preflight-targets`, `canary-targets`) are explicitly non-deterministic by design and not part of the planning-execution boundary, as they serve separate diagnostic purposes.

**[Existing Precedent]**

- R8. The document MUST cite `validate/engine.py` as the canonical example of a PURE compute contract — annotated with what it MUST NOT do, returning typed results rather than emitting I/O.
- R9. The document MUST cite `ledger.aggregate.build_ledger` and `plan_backlinks/_engine.py` as additional precedents following the same pattern, noting that only validate/engine.py currently carries an explicit purity annotation.

**[Guidance for New Development]**

- R10. The document SHOULD include guiding principles for deciding where new functionality belongs:
  - Can it be computed from existing data without I/O? → planning step
  - Does it require external platform state? → execution/publishing step
  - Does it require network I/O but produce data planning needs? → non-deterministic input (must be called out as such)

---

## Success Criteria

- A downstream reader (new contributor, or agent during ce-plan) can determine for any new feature whether it belongs in planning or publishing by reading the principle doc, without inspecting existing code.
- An engineer can determine what needs mocking in planning tests by consulting the doc's non-deterministic dependency list.
- The doc is short enough to be included as a reference in AGENTS.md or a future ARCHITECTURE.md without bloating those files.

---

## Scope Boundaries

- Code refactoring to enforce the separation (e.g., pulling content_fetch out of plan-backlinks) — this document is an architecture principle, not a refactor plan
- Adding purity tests or test fixtures for planning — deferred to a follow-up if the doc proves useful
- CI gates to enforce purity — deferred; enforcement is downstream of the principle being established
- Changes to existing code behavior or monolith budgets
- Implementation details (file paths, code shapes, schemas, migration strategies)

---

## Key Decisions

1. **Pipeline-level boundary with callouts (not module-level enforcement).** Drawing the line at the command level (plan | validate | publish) matches the existing architecture and avoids churn. Module-level enforcement would force annotation of every sub-module without changing the output contract. The non-deterministic dependencies inside planning are called out explicitly as external inputs, which is sufficient for the principle to be actionable.

2. **Content_fetch as non-deterministic input (not a separate pipeline phase).** Rather than redesigning planning into a multi-phase process (acquire → compute), the doc treats fetched content as an input to the pure planning kernel. This matches current architecture and minimizes disruption while still establishing the boundary.

3. **Validate-backlinks' dual nature is an explicit exception.** Rather than forcing validate into a single category, the doc treats its pure engine as the contract and the URL probes as an optional pre-flight. This preserves validate/engine.py's purity without losing useful diagnostics.

---

## Dependencies / Assumptions

- The existing `validate/engine.py` purity contract is the right model for the principle — it demonstrates what "pure" means in this codebase
- `content_fetch` and LLM calls will remain as planning inputs (no separate acquisition phase is being proposed)
- The document is advisory — it codifies the principle for future reference, not as an enforceable CI gate
- Readers are familiar with the pipeline at the command level (documented in AGENTS.md)
- All codebase references (validate/engine.py, plan_backlinks/_engine.py, ledger.aggregate.build_ledger) exist at their canonical paths at time of writing


## Outcome (2026-06-01)

Shipped → `docs/plans/2026-05-28-002-feat-deterministic-planning-purity-plan.md` (status: active).