# ce:review — R8 Cycle Panel (plan 2026-06-08-001)
Run date: 2026-06-08  
Base: `39d7b2bb68a24da7610b63733522c4baf35c0fc7`  
Branch: `feat/plan004-keepalive-recovery-loop`  
Mode: autofix  
Reviewers: 10 (correctness, security, testing, maintainability, reliability, api-contract, adversarial, kieran-python, project-standards, agent-native) + learnings-researcher

---

## Applied Safe-Auto Fixes (5)

### F1 — `None` target_url → AttributeError in `reset_exhausted()`
`webui_app/routes/keep_alive.py:142`  
`body.get("target_url", "").strip()` → `(body.get("target_url") or "").strip()`  
When JSON body sends `{"target_url": null}`, `.get(key, "")` returns `None` (key exists),  
and `None.strip()` raises `AttributeError`. The `or ""` coercion handles both absent and null.

### F2 — Non-dict retry_counts entries crash exhausted-list build
`webui_app/services/keep_alive.py:177-187`  
Added `isinstance(entry, dict)` guard in list-comprehension filter.  
Corrupted state files with non-dict retry_counts values would raise `AttributeError: 'int' object has no attribute 'get'`.

### F3 — Non-numeric `attempts` value raises `ValueError` in `int()`
`webui_app/services/keep_alive.py:180,186`  
`int(entry.get("attempts", 0))` → `int(entry.get("attempts") or 0)`  
Handles `None` (explicit JSON null) and avoids crashing on falsy values.

### F4 — Sort key TypeError when `last_attempt_at` is an int (legacy unix timestamp)
`webui_app/services/keep_alive.py:188`  
`e.get("last_attempt_at") or ""` → `str(e.get("last_attempt_at") or "")`  
Mixed int/str sort keys raise `TypeError: '<' not supported between instances of 'int' and 'str'` on Python 3.

### F5 — `int(None)` crash in platform stats + missing `# noqa: BLE001`
`webui_app/services/keep_alive.py:209-213`  
`int(pstats.get("alive_count", 0))` → `int(pstats.get("alive_count") or 0)`  
(same for `total_published`). Also added `# noqa: BLE001` to bare `except Exception`.

---

## Residual Actionable Work (downstream-resolver)

### R1 — ARV-004: `MAX_RETRY=0` causes all targets to appear immediately exhausted
`src/backlink_publisher/keepalive/run_state.py` — `MAX_RETRY` property has no range validation.  
`KEEPALIVE_MAX_RETRY=0` → every target with `attempts=0` passes `>= 0`, making the cycle a no-op.  
**Fix:** `return max(1, int(os.environ.get("KEEPALIVE_MAX_RETRY", 3)))` in the property getter.  
Owner: downstream-resolver, severity P2.

### R2 — ARV-005: URL non-canonicalization in `reset_exhausted()` silently fails
`webui_app/routes/keep_alive.py` — `target_url` from the request body is used as-is as the dict key.  
If the client sends a URL variant that differs from how `record_attempt()` stored it (trailing slash, encoding),  
`rs.reset_exhausted(target_url)` silently pops nothing and returns `was_present=False`.  
**Fix:** Verify whether `record_attempt()` canonicalizes before storing; if not, apply the same normalization in the route.  
Owner: downstream-resolver, severity P2. Requires investigation.

### R3 — C1: 403 Origin-guard returns HTML, not JSON
`webui_app/routes/keep_alive.py` — `_check_bind_origin_or_abort()` calls `abort(403)` → HTML response.  
`cycle-panel.js` catches this in `doReset()` and shows a generic error message.  
Not a regression (all origin-guarded routes share this behavior); fix by adding an app-level `@app.errorhandler(403)` that returns JSON, or wrapping `abort(403)` in the route.  
Owner: downstream-resolver, severity P1 (UX impact only, no data loss).

### R4 — AGENT-001: No CLI entry point for `reset-exhausted`
`pyproject.toml` — `keepalive-reset-exhausted` is not a console script.  
Agents calling the operation must either use HTTP (with Origin header + CSRF) or bury it in `keepalive-status --reset-exhausted`.  
**Fix:** Export a dedicated `keepalive-reset-exhausted <url>` CLI tool.  
Owner: downstream-resolver, severity P1 (agent-native parity gap).

---

## Advisory Outputs

- **ARV-003 (sort key):** Fixed. Int-vs-str sort is now guarded by `str()` coercion.
- **Maintainability:** Truncation limit `20` is a magic constant. Consider `_EXHAUSTED_LIST_DISPLAY_LIMIT = 20` in a follow-up if the value changes.
- **Testing gap:** No test for `MAX_RETRY=0` edge case in `KeepaliveRunState`.
- **Testing gap:** No test for `weight=0.0` + `locked=True` boundary (circuit_broken should be False).
- **Security:** `was_present` field leakage is an accepted trade-off (operator-only tool).
- **Reliability:** Cross-process read race on `keepalive_run_state.json` is accepted (matches `/optimization-status` precedent).
- **Learnings applied:** `sys.modules` pytest-detect pattern confirmed correct (no new app-level guard added). `atomic_write` TOCTOU risk is accepted per existing design.

---

## Test Run
179 passed, 4 warnings — all green post-fix.
