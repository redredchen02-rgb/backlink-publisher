# Deterministic Planning ↔ Non-Deterministic Execution Principle

**Status:** Advisory — codifies the architecture boundary; not enforced by CI or tests.

> **Principle:** Planning is deterministic and testable. Publishing depends on external platform state.

---

## Pipeline Command Boundary

| Command | Nature | Rationale |
|---|---|---|
| `plan-backlinks` | **Deterministic with non-deterministic inputs** | Engine (link building, templates, payload assembly) is pure computation. Content fetch, LLM calls, and image gen are external inputs that feed the engine — not part of the planning kernel. |
| `validate-backlinks` | **Deterministic (pure engine)** | Engine is explicitly PURE (see [Existing Precedent](#existing-precedent)). The optional `--no-validate-url-check` flag gates URL reachability probes — the only non-deterministic path. The pure engine is the contract; URL probes are an optional pre-flight. |
| `publish-backlinks` | **Non-deterministic** | Platform API calls, auth state, rate limits, and network failures are inherently non-deterministic. The policy layer (circuit breaker, health gate, retry, dedup) manages this non-determinism, not eliminates it. |

---

## Non-Deterministic Dependencies

These are external inputs that feed deterministic planning steps. They are **not** part of planning computation:

| Dependency | Source of non-determinism |
|---|---|
| `content.fetch` | Network I/O — seed content retrieval may vary by time, network state |
| LLM API calls | Anchor text generation — non-deterministic by nature (same prompt → different output) |
| Image generation API | Banner artwork — network I/O, non-deterministic output |
| `linkcheck.http` | URL reachability — depends on remote server state |

When testing planning code, mock these dependencies. The planning kernel itself should be testable with deterministic inputs.

---

## Exceptions and Edge Cases

### Validate-backlinks dual nature

`validate-backlinks` has a **pure engine** as its contract. The engine (`validate/engine.py`) returns typed results, does not touch I/O, and is fully testable with mock inputs. The optional `--no-validate-url-check` flag controls URL reachability probes, which are the only non-deterministic path. This design is intentional — the pure path is the default; diagnostics that require network I/O are opt-in.

### Read-only diagnostic commands

| Command | Nature |
|---|---|
| `preflight-targets` | Non-deterministic by design — destination-page health check before publish. Not part of the planning-execution boundary. |
| `canary-targets` | Non-deterministic — verifies dofollow integrity by re-fetching live posts. Separate diagnostic, not planning. |
| `audit-state` | Read-only — dual-state divergence auditor. No network I/O, advisory-only. |

These commands serve separate diagnostic purposes and are not constrained by the planning/publishing boundary.

---

## Existing Precedent

The project already has implementations that demonstrate this principle:

**`validate/engine.py`** — the canonical pure engine. Its docstring states:
> "This module is PURE compute. It MUST NOT: touch sys.stdout / sys.stderr, call set_log_level, raise SystemExit, read stdin / write stdout / emit the config_echo banner / do recon logging."

It returns a typed `ValidateOutcome` and lets the CLI shell handle all I/O. This is the model for what "pure" means in this codebase.

**`ledger.aggregate.build_ledger`** — follows the same engine/shell pattern. Pure computation, caller handles I/O.

**`plan_backlinks/_engine.py`** — the planning kernel (link building, templates, payload). Largely pure, but currently lacks an explicit purity annotation. Follows the same pattern by convention.

---

## Guidance for New Development

When deciding where a new capability belongs:

| If it... | Then it belongs in... |
|---|---|
| Can be computed from existing data without I/O | Planning step (deterministic) |
| Requires external platform state | Execution / publishing step (non-deterministic) |
| Requires network I/O but produces data planning needs | Non-deterministic input — call out explicitly as an external dependency of planning |

### Choosing a command

- If the new code is pure computation → extend an existing engine module
- If it requires platform API calls or auth → extend publish-backlinks or an adapter
- If it needs network I/O but the result is advisory (not gating execution) → consider a standalone diagnostic command (like `preflight-targets` or `canary-targets`)
- If it reads but does not modify pipeline state → keep it read-only, exit 0

---

## References

- Plan: `docs/plans/2026-05-28-002-feat-deterministic-planning-purity-plan.md`
- Requirements: `docs/brainstorms/2026-05-28-deterministic-planning-purity-requirements.md`
- AGENTS.md — canonical project reference
