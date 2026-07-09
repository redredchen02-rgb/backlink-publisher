# Debt Registry Triage — 2026-07-07

Unit 2 of `docs/plans/2026-07-07-003-opt-backend-code-health-optimization-plan.md`
(canonical checkout — not yet present in this worktree at plan-authoring time).
Scope: the 43 `[[items]]` entries in `debt_registry.toml` with `status = "accepted"`
as of this audit. Method: for each entry, read its `location` (or the described
area, for the one entry with no `location`), confirm the `except`/fallback
pattern the `rationale` describes is still literally present in the code, and
classify.

Classification legend (per the plan's three buckets):
- **A — still valid**: keep `accepted` as-is.
- **B — resolved-candidate**: the flagged pattern has genuinely disappeared;
  safe to flip to `resolved` (requires concrete evidence quoted below).
- **C — needs human re-evaluation**: condition looks worse, or `location` is
  stale/moved; status left untouched.

## Result summary

- **43/43** classified **A (still valid)** — no entries met the bar for B or C
  in the "condition changed" sense.
- **5 of the 43** additionally carry a **location-staleness note** (line
  numbers drifted by a few lines due to unrelated edits elsewhere in the same
  file — the `# debt: <slug>` comment and the pattern it documents are both
  still present and correct). These are recorded as a sub-flag on otherwise-A
  entries per the plan's own "location invalidated by file move" edge case —
  not reclassified to C, since the *condition* is unchanged, but flagged so a
  follow-up mechanical patch can refresh the four line numbers.
- **`debt_registry.toml` was left unmodified.** Zero entries met bucket B's bar
  (concrete evidence the flagged pattern is gone), so step 6's "only touch the
  registry for confident flips" condition was never triggered. The freshness-
  claim mechanism named in the task (`test_every_resolved_or_mitigated_item_has_a_freshness_claim`
  or equivalent) does **not** exist in this codebase's `tests/test_debt_registry_format.py`
  — the closest analog is `test_no_stale_mitigated_items`, which only checks
  `status == "mitigated"` items older than 90 days, not `resolved` ones. This
  is moot here since nothing was flipped.

## Verification method

Grepped every `# debt: <slug>` comment under `src/` and `webui_app/`
(`_scan_debt_comments` in `tests/test_debt_registry_format.py` does the same
scan for its cross-reference test) and diffed the resulting `(slug, file,
line)` triples against each entry's `location` array. For entries with no
`location` field (`no-debt-tracking`), confirmed the described condition
(existence/use of the registry itself) directly. Then read a ~10-40 line
window around each location to confirm the actual `except` clause types and
fallback behavior still match the entry's `rationale` prose.

Six directories (`events/`, `gap/`, `idempotency/`, `ledger/`, `_util/`,
`webui_app/api/`) are hard cross-reference-enforced by
`test_cross_reference_debt_comments_have_registry_entries` (exact line match
required); everything else (`webui_app/helpers/`,
`publishing/adapters/`, `cli/**`) is not line-exact-enforced by any test, so
minor line drift there is currently silent (no CI failure) but still noted
below.

## Per-item classification

| # | slug | class | evidence |
|---|------|-------|----------|
| 1 | `no-debt-tracking` | A | No `location` (pre-D2, registry-only). Self-referential claim ("the registry itself resolves this") remains true — `debt_registry.toml` exists, is actively maintained (58 entries, dated as recently as 2026-07-06), and is test-enforced by `tests/test_debt_registry_format.py`. |
| 2 | `reconciler-history-dedupkey-parse-failure` | A | `events/reconciler.py:385-387` — `except (ValueError, TypeError): ... continue` around `DedupKey(...)` construction, exact match to rationale. |
| 3 | `gap-derive-host-urlparse-failure` | A | `gap/events_gap.py:242-244` — `except (ValueError, TypeError): return target_url`, exact match. |
| 4 | `webui-token-paste-file-read-failure` | A | `webui_app/helpers/contexts.py:117-119` — `except (OSError, ValueError): data = None`, exact match. |
| 5 | `webui-render-queue-load-failure` | A (location stale) | Pattern intact but registry's `location` says `webui_app/helpers/contexts.py:357`; the `# debt: webui-render-queue-load-failure` comment is now at line **356** (drifted by 1, from an unrelated edit earlier in the file). Not seam-scanned, so no test currently fails. Recommend a follow-up 1-line location fix, not a status change. |
| 6 | `webui-render-image-gen-status-failure` | A (location stale) | Same file; registry says `:375`, comment now at line **374** (same 1-line drift as #5). Not seam-scanned. Recommend follow-up location fix only. |
| 7 | `net-safety-dns-resolve-oserror` | A | `_util/net_safety.py:80-82` — `except OSError: return [], "dns_failure"` (distinct from the `socket.gaierror` branch above it), exact match; fail-closed SSRF-guard contract confirmed intact. |
| 8 | `dedup-gate-key-canonicalization-failure` | A | `cli/_dedup_gate.py:90-92` — `except (ValueError, TypeError): return None`, exact match. |
| 9 | `keepalive-status-relative-ts-parse-failure` | A | `cli/ops/keepalive_status.py:30-32` — `except (ValueError, TypeError): return iso or "never"`, exact match. |
| 10 | `probe-citations-strip-scheme-host-parse-failure` | A | `cli/ops/probe_citations.py:464-466` — `except (ValueError, TypeError): return url`, exact match. |
| 11 | `pr-opportunities-config-targets-load-failure` | A | `cli/pr_opportunities.py:43-45` — `except (FileNotFoundError, ValueError, TypeError): return {}`; function's own docstring still documents "or {} on any error", exact match. |
| 12 | `spray-audit-link-concentration-informational-failure` | A | `cli/spray_backlinks/_audit.py:79-81` — `except (ImportError, TypeError, ValueError, ZeroDivisionError): return None`, exact match. |
| 13 | `config-tokens-load-token-parse-failure` | A | `config/tokens.py:75-77` — `except (json.JSONDecodeError, OSError): return None`, exact match. |
| 14 | `errors-emit-envelope-broad-catch` | A | `_util/errors.py:204-206` — genuinely broad `except Exception: pass` at process-exit time, exact match to the deliberate-broad-catch rationale. |
| 15 | `idempotency-store-rollback-failure` | A | `idempotency/store.py:242-244` — ROLLBACK wrapped in `except sqlite3.Error: pass` inside an outer handler that still always re-raises the original exception, exact match. |
| 16 | `campaign-bootstrap-status-fail-soft` | A | `webui_app/api/campaign_api.py:62/68/72` — all 3 cascading sites present exactly as described (`channel_status.list_all()` → `{}`, `verify_health` merge → pass, outer → `None`). |
| 17 | `campaign-worker-dispatch-best-effort` | A | `webui_app/api/campaign_api.py:108-110` — dispatch to `CAMPAIGN_WORKER` wrapped in `except Exception: pass`, after the store write already succeeded, exact match. |
| 18 | `image-gen-probe-payload-parse-fallback` | A | `webui_app/api/image_gen_diagnostics_api.py:62-64` and `:102-104` — both `_probe_openai`/`_probe_frw` optional-field parses wrapped in bare `except Exception: pass`, exact match. |
| 19 | `image-gen-test-connection-envelope-catchall` | A | Same file `:129-133` and `:152-155` — both log `type(exc).__name__` server-side and return only the class name (the documented 2026-07-02 D2 redaction fix is present), exact match. |
| 20 | `image-gen-generate-sample-envelope-catchall` | A | Same file `:169-173` and `:212-215` — same redaction pattern confirmed, exact match. |
| 21 | `llm-diagnostics-run-connection-error-envelope` | A | `webui_app/api/llm_diagnostics_api.py:172-175` and `:176-179` — both log `type(e).__name__` and return only the class name, exact match. |
| 22 | `llm-diagnostics-test-generation-error-envelope` | A | Same file `:215-220` — same redaction pattern, exact match. |
| 23 | `scheduled-list-read-fail-open` | A | `webui_app/api/scheduled_api.py:21-24` — logs `type(exc).__name__`, degrades to `{"ok": False, "items": []}`, exact match. |
| 24 | `sites-next-run-scheduler-lookup-fail-open` | A | `webui_app/api/sites_api.py:94-96` — APScheduler `get_job` lookup wrapped in `except Exception: return None`, exact match. |
| 25 | `sites-scheduler-job-removal-best-effort` | A | Same file `:319-321` — job removal wrapped in `except Exception: pass` after the `schedule_store` mutation already applied, exact match. |
| 26 | `sites-autopilot-scheduler-sync-rollback` | A | Same file `:322-338` — except-block explicitly rolls back the `schedule_store` mutation and returns `SCHEDULER_SYNC_FAILED` with `type(exc).__name__` only, exact match. |
| 27 | `sites-scrape-preview-fail-safe` | A | Same file `:364-366` — `except Exception as exc: return {"status": "error", "reason": type(exc).__name__}`, exact match. |
| 28 | `sites-citation-alert-fail-open` | A | Same file `:435-437` — file read/parse wrapped in `except Exception: return None`, exact match. |
| 29 | `monitor-summary-aggregator-fail-open` | A | `webui_app/api/v1/monitor.py:54-56` — outer `except Exception` degrades to `cards=[], degraded=True`, exact match; each subsystem still degrades individually first, matching the "belt-and-suspenders" framing. |
| 30 | `pipeline-regen-body-config-load-error` | A | `webui_app/api/v1/pipeline.py:273-277` — `except Exception as exc: raise ApiProblem(422, ..., detail=type(exc).__name__, ...)`, exact match; raw exception text not echoed. |
| 31 | `pipeline-regen-body-llm-call-error-redacted` | A | Same file `:310-316` — uses the shared `_redact_for_log(str(exc))` helper before raising `ApiProblem(502, ...)`, exact match. |
| 32 | `medium-browser-captcha-probe-reraise-accepted` | A (location stale) | Pattern intact (bare except around the CAPTCHA-iframe probe still only logs; the enclosing `raise` still re-raises the original `PlaywrightTimeoutError`). Registry says `publishing/adapters/medium_browser.py:285`; comment now at line **280** (drifted by 5 lines from earlier edits in the same file, e.g. the resolved `medium-browser-save-draft-false-success-fixed` fix). Not seam-scanned. Recommend follow-up location fix only. |
| 33 | `medium-browser-tag-insertion-best-effort-accepted` | A (location stale) | Pattern intact (tag-insertion loop still `except: log 'tag insertion failed (optional)'`). Registry says `:337`; comment now at line **332** (same drift source as #32). Recommend follow-up location fix only. |
| 34 | `medium-browser-mark-expired-swallow-accepted` | A (location stale) | Pattern intact (`_safe_mark_expired` still swallows and logs a warning before the caller's `AuthExpiredError` fires). Registry says `:159`; comment now at line **154** (same drift source). Recommend follow-up location fix only. |
| 35 | `project-helpers-ensure-article-fallback-degrade-accepted` | A | `events/_project_helpers.py:263-269` — both the nested `IntegrityError` fallback lookup and the outer except still degrade to `return None`; docstring still says "Never raises — returns None on an empty url or any store failure", exact match. |
| 36 | `project-helpers-write-quarantines-log-failure-accepted` | A | Same file `:156-171` — quarantine write failure still logs at error level and continues the loop rather than raising, exact match. |
| 37 | `projector-record-health-self-protect-accepted` | A | `events/projector.py:90-105` — health-marker write still wrapped in `except Exception: log.warning(...)`, self-protecting swallow as described, exact match. |
| 38 | `reconcile-project-on-read-degrade-accepted` | A | `events/reconcile.py:84-92` — `except Exception as exc: return ReadProjectionResult(degraded=True, degraded_reason=...)`; docstring still says "NEVER raises", exact match. |
| 39 | `reconcile-quarantine-helpers-best-effort-accepted` | A | Same file, all 6 sites (`:197`, `:210`, `:245`, `:256`, `:271`, `:289`) confirmed: `_latest_event_utc`→`None`, `_open_quarantine_count`→`0`, `_quarantine`/`_clear_quarantine`/`_clear_quarantine_by_dedup_key`→log-only, `_get_reconciler_quarantine_set`→empty set. None produce/gate an authoritative field. |
| 40 | `reconciler-checkpoint-crossref-fail-closed-accepted` | A | `events/reconciler.py:166/215/312` — all 3 sites confirmed: DedupKey-construction fail-closed drop, auto-fix except-log (no false "done" write), batched dedup-read except-log-return. |
| 41 | `reconciler-history-reverse-check-batch-read-accepted` | A | Same file `:396` — batched dedup-store read failure still reports zero gaps for the batch rather than raising, exact match; report-only R4 contract confirmed via `cli/publish/_publish_helpers.py` / `cli/_publish_helpers.py` still only forwarding the summary dict. |
| 42 | `reconciler-log-and-canonicalize-best-effort-accepted` | A | Same file `:105` and `:121` — RECON.log append swallow and `_canonicalize_url` wrapper (→`None`) both confirmed, exact match. |
| 43 | `reconciler-reconcile-all-outer-degrade-accepted` | A | Same file `:456` — outer except around both phases still degrades to the partial `ReconciliationSummary`; docstring still literally says "Never raises — errors degrade to partial results", exact match. |

## Location-staleness follow-up (mechanical, not a status change)

Five entries have `location` line numbers off by 1-5 lines from unrelated
edits elsewhere in the same file (none in a seam-scanned directory, so no CI
gate currently fails):

| slug | file | registry says | comment now at |
|------|------|---------------|-----------------|
| `webui-render-queue-load-failure` | `webui_app/helpers/contexts.py` | 357 | 356 |
| `webui-render-image-gen-status-failure` | `webui_app/helpers/contexts.py` | 375 | 374 |
| `medium-browser-mark-expired-swallow-accepted` | `publishing/adapters/medium_browser.py` | 159 | 154 |
| `medium-browser-captcha-probe-reraise-accepted` | `publishing/adapters/medium_browser.py` | 285 | 280 |
| `medium-browser-tag-insertion-best-effort-accepted` | `publishing/adapters/medium_browser.py` | 337 | 332 |

Recommend a small follow-up PR (or the next unit that touches these files
anyway, e.g. Unit 3's `medium_browser.py` adapter cleanup) refresh these 5
line numbers in `debt_registry.toml`. Left untouched here per the task's
"only change status you're confident about" instruction — this is not a
status change, just stale metadata, and bundling an unrelated registry edit
into an audit-only unit risked touching lines Unit 3 is about to edit anyway.

## `debt_registry.toml` changes made by this unit

None. All 43 `accepted` entries are classified **A**; zero met the bar for
**B** (resolved-candidate). No edits were made to the file.
