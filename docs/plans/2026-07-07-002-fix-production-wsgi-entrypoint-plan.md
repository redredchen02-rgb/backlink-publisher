---
title: Replace Werkzeug dev server with a production WSGI entrypoint
type: fix
status: completed
date: 2026-07-07
---

# Replace Werkzeug dev server with a production WSGI entrypoint

## Overview

The WebUI is launched today via `python webui.py`, which calls Flask's
`app.run(...)` — the Werkzeug development server. Every startup prints
Werkzeug's standard warning ("This is a development server. Do not use it in
a production deployment. Use a production WSGI server instead."), which is
what prompted this plan.

**Scope, as confirmed with the user:** swap the dev server for a real WSGI
server for the *existing* deployment topology only — same machine, loopback
bind, no authentication. This plan does **not** open the WebUI to other
machines, add authentication, or add TLS. Those would be a materially
larger, separate effort (see Scope Boundaries).

`waitress>=3.0,<4` is already a declared core dependency in `pyproject.toml`
but is never imported anywhere in the codebase — it appears to have been
added in anticipation of exactly this change and never wired up.

## Problem Frame

`webui.py`'s `__main__` block calls `app.run(host=bind_host, port=port,
debug=debug_mode, use_reloader=False)`. This is fine for interactive
development (it's how `FLASK_DEBUG=1` gets you the Werkzeug debugger) but
is explicitly unsupported by Werkzeug for anything else — no production
hardening, no real concurrency model, and the startup banner says so every
time.

Research surfaced that this is not a purely cosmetic fix — it closes a
pre-existing, confirmed-dead code path:

- `Dockerfile` (`dev` and `runtime` stages) already ends in `CMD ["python",
  "serve.py"]`, and `docker-compose.yml` builds from the same image. A prior
  plan's execution log (`docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`,
  U2 execution note, 2026-07-06) confirmed by direct git-history search that
  `serve.py` **has never existed in this repo**, since the commit that
  introduced the Dockerfile (`69c2d9be`). The container entrypoint is dead.
- The macOS restart path, `restart_webui.sh` (workspace root, untracked),
  already runs `nohup "$PY" serve.py &` — also currently broken for the same
  reason. `restart_webui.bat` (Windows equivalent) already special-cases
  `*serve.py*` in its process-kill matcher, anticipating the same rename.
- `scripts/launcher.command` / `scripts/launcher.ps1` (the two git-tracked,
  "one launcher" canonical scripts per AGENTS.md R9) and the untracked
  workspace-root `.bat`/`.command` launchers all currently invoke
  `webui.py` directly — this is the actual code path the user hit the
  warning through.

So the fix is: add the missing `serve.py`, and point every launcher that
should run production-style at it instead of `webui.py`.

## Requirements Trace

- R1. Production launches must not use the Werkzeug dev server, for the
  existing loopback-only, no-auth topology.
- R2. `serve.py` must exist and actually serve the app (currently referenced
  by `Dockerfile` and `restart_webui.sh` but absent).
- R3. The security posture must not regress: bind stays loopback-only
  (`_resolve_bind_host()` unchanged), `FLASK_DEBUG`/Werkzeug interactive
  debugger must never be reachable through the production entrypoint.
- R4. No new concurrency bugs: a documented pre-existing gap in the legacy
  `POST /ce:draft/bulk-publish-now` route (`webui_app/routes/drafts.py`, no
  lock — documented in a comment at `webui_app/api/v1/drafts.py:44-52` on
  the sibling `/api/v1` route, which itself already has a lock) relies on
  the dev server's de facto single-threaded request handling to avoid a
  double-schedule race. Switching WSGI servers must not silently turn that
  into a live race.

## Scope Boundaries

- Not opening the WebUI to non-loopback hosts. `_resolve_bind_host()`
  continues to unconditionally refuse any `BIND_HOST` other than a loopback
  address — this plan does not touch that function.
- Not adding authentication, TLS, or a reverse proxy.
- Not fixing Docker/`docker-compose` deployment end-to-end. Even with
  `serve.py` present, `docker-compose.yml`/`Dockerfile` set
  `BIND_HOST=0.0.0.0`, which `_resolve_bind_host()` will still hard-refuse
  with `RuntimeError` at startup — a second, independent reason the
  container path is dead today. Resolving that requires deciding whether
  containers get a bind-security exception or a reverse-proxy model, which
  is exactly the "open to other machines" scope the user declined. `serve.py`
  existing is a prerequisite for that future work, not a fix for it.
- Not restructuring the workspace-root launchers to delegate to
  `scripts/launcher.ps1`/`launcher.command` (the AGENTS.md R9 "thin entry
  point" ideal). That drift is pre-existing and was already explicitly
  deferred by a prior plan (`docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`,
  Deferred to Separate Tasks) as unrelated architectural cleanup. This plan
  only changes which script filename each launcher invokes at its existing
  final launch line.
- Not touching `.github/workflows/api-contract.yml`, which intentionally
  runs `python webui.py &` as an ephemeral fuzz-test harness — that's a
  correct use of the dev server for CI, not a production deployment.

### Deferred to Separate Tasks

- Container ("Docker revival") deployment: needs a decision on non-loopback
  bind exception or reverse-proxy termination, plus fixing
  `_resolve_bind_host()`'s interaction with `BIND_HOST=0.0.0.0` — separate,
  larger task per the user's chosen scope.
- Workspace-root launcher consolidation onto `scripts/launcher.ps1` /
  `scripts/launcher.command` (R9 thin-entry-point ideal) — pre-existing
  architectural debt, tracked as deferred by a prior plan already.

## Context & Research

### Relevant Code and Patterns

- `webui.py:22-34,101-113` — `_resolve_debug_mode()` (fail-safe, default
  OFF, RCE-risk rationale documented inline), module-level `app =
  create_app()` with an explicit comment: "required so `from webui import
  app` works (legacy tests, WSGI servers, debug tooling)" — this is the
  intended integration seam for a WSGI launcher; `serve.py` should import
  `app` from `webui`, not call `create_app()` a second time.
- `webui_app/helpers/security.py:89-108` — `_resolve_bind_host()`: reads
  `BIND_HOST` (default `127.0.0.1`), unconditionally raises `RuntimeError`
  for anything non-loopback, regardless of
  `BACKLINK_PUBLISHER_ALLOW_NETWORK`. `serve.py` must call this same
  helper, not re-derive bind logic.
- `webui_app/helpers/cli_runner.py::_wire_content_fetch_ttl_from_env` —
  called by `webui.py` before `app.run(...)`; `serve.py` needs the same
  call for parity.
- `webui_app/api/v1/drafts.py:39-52` — a comment on this file's own
  (already-locked) `/api/v1` bulk-publish-now route documents the actual
  gap: `webui_app/routes/drafts.py`'s legacy route has no lock, and the
  comment explicitly says this is "low practical urgency today" only
  because `app.run()` has no `threaded=True`. This is the concrete reason
  `serve.py` must not default to multi-threaded serving. (An earlier draft
  of this plan and of `serve.py`'s warning text misattributed the missing
  lock to `api/v1/drafts.py` itself — caught and fixed during the code
  review pass; see Risks & Dependencies.)
- `scripts/launcher.command` (macOS, git-tracked canonical, `WEBUI_SCRIPT`
  variable defaults to `webui.py`, already overridable via env for the
  manual crash-stub test) and `scripts/launcher.ps1` (Windows git-tracked
  canonical, hardcoded `& $PY webui.py`).
- Workspace-root (untracked, outside the `backlink-publisher/` git repo):
  `start-webui.bat`, `启动WebUI.bat`, `restart_webui.bat` all end with
  `"%PY%" webui.py`; `restart_webui.sh` and `启动WebUI.command` already say
  `serve.py`.
- `pyproject.toml:26` — `"waitress>=3.0,<4"` already declared; no dependency
  change needed.

### Institutional Learnings

- `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md` (U2
  execution note, 2026-07-06): confirms via full git-history search that
  `serve.py` referenced in `Dockerfile` has never existed; flags both the
  missing-file and the `BIND_HOST=0.0.0.0` vs. loopback-enforcement
  conflict as out of scope for that PR, needing a future "container
  revival" task.
- `docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`: flags
  the workspace-root `.bat` launchers as pre-existing R9 drift (should
  delegate to `scripts/launcher.ps1` rather than duplicate its logic) and
  explicitly defers fixing that; also defers adding stdio-encoding
  safeguards to `serve.py`'s (not-yet-existing) startup path for headless
  deployment, treating it as a distinct future topology.
- `AGENTS.md` "One launcher (R9)": canonical launchers are
  `scripts/launcher.command` (macOS) / `scripts/launcher.ps1` (Windows); the
  workspace-root `.bat`/`.command` files are meant to be thin wrappers
  around them but currently duplicate logic (known, deferred drift, see
  Scope Boundaries).

## Key Technical Decisions

- **`serve.py` imports `from webui import app` rather than calling
  `create_app()` itself.** `webui.py` already documents this as the
  intended seam ("required so `from webui import app` works ... WSGI
  servers"). Avoids a second app-construction path drifting from the dev
  entrypoint's.
- **`waitress.serve(..., threads=1)` by default, overridable via
  `WSGI_THREADS`, with `_resolve_threads()` rejecting values below 1.**
  `webui_app/routes/drafts.py`'s legacy bulk-publish-now route has a real,
  currently-latent race (no lock) that is only safe because today's dev
  server can't serve two requests concurrently — confirmed independently
  during the code-review pass by
  `docs/solutions/ux-honesty/webui-false-success-resolution.md`, which
  documents the same route's store-update-then-scheduler.add_job pair as
  non-atomic, so `threads=1` is doing real defensive work here, not just
  being conservative. Defaulting to 1 thread preserves that same effective
  serialization exactly, so this plan introduces zero new concurrency
  exposure. Raising the thread count later is a separate, deliberate
  decision that should first close the drafts.py gap. Because the only
  thing standing between a safe default and a live race is one
  environment variable, `serve.py` also emits a loud startup warning
  naming the drafts.py gap whenever `WSGI_THREADS` resolves above 1 (see
  Unit 1) — a source comment and this plan document are not something a
  future operator tuning throughput in a deploy config is likely to
  consult, so the warning has to live where it will actually be seen: at
  startup, in the process they're launching. `_resolve_threads()` treats
  `WSGI_THREADS<=0` or non-numeric values as a hard error rather than
  silently accepting them — waitress's own thread dispatcher never starts a
  worker when `threads<=0` (verified against the vendored waitress 3.0.2
  source during code review), which would silently hang every request
  forever, a strictly worse failure mode than the race this default
  guards against.
- **`serve.py` forces `app.debug = False` before serving, independent of
  `FLASK_DEBUG`.** Waitress has no Werkzeug-style interactive debugger, but
  leaving `app.debug` however `create_app()`/Flask left it risks verbose
  tracebacks in error responses. Production entrypoint hard-disables it as
  defense-in-depth rather than trusting env-var hygiene at every call site.
- **Reuse `_resolve_bind_host()` and `_wire_content_fetch_ttl_from_env()`
  unchanged.** No new bind or startup logic — only the server that consumes
  the resolved host/port changes.
- **Only the final launch line changes in each launcher script** (`webui.py`
  → `serve.py`), not their structure. Keeps this plan mechanically small and
  avoids re-opening the already-deferred R9 launcher-consolidation and
  Docker-bind decisions.
- **`webui.py`'s own `__main__` block is untouched.** `python webui.py`
  remains the interactive/debug entrypoint (e.g., for `FLASK_DEBUG=1`); only
  launchers that are meant to run "for real" switch to `serve.py`.

## Open Questions

### Resolved During Planning

- Does adding `serve.py` fix Docker deployment? No — `_resolve_bind_host()`
  will still reject `BIND_HOST=0.0.0.0` at startup. Explicitly out of scope
  (see Scope Boundaries); `serve.py` existing is a prerequisite for, not a
  resolution of, that future work.
- Should `serve.py` default to multiple threads for better throughput? No —
  see Key Technical Decisions; the drafts.py single-flight gap makes
  `threads=1` the only safe default without also fixing that gap in the
  same change.

### Deferred to Implementation

- Exact wording of the startup banner/log lines `serve.py` prints — cosmetic,
  implementer's call, should clearly say "production (waitress)" so it's
  visually distinct from the dev-server banner.
- ~~Whether the crash-restart loop in `scripts/launcher.command` needs its
  hardcoded "webui.py crash" log strings updated to reference
  `$WEBUI_SCRIPT` dynamically~~ — resolved during Unit 2: yes, updated both
  crash-log lines to interpolate `$WEBUI_SCRIPT`. Also discovered and fixed
  during implementation: `is_our_webui()`'s stale-process detector had the
  same `*webui.py*`-only gap as the Unit 3 `.bat` finding — a leftover
  `serve.py` process wouldn't have been recognized as "ours" for port reuse.
  Fixed to match `$WEBUI_SCRIPT` dynamically, same file.

## Implementation Units

- [x] **Unit 1: Add `serve.py` production WSGI entrypoint**

**Goal:** A working, loopback-only, single-threaded-by-default waitress
entrypoint that serves the exact same `app` as `webui.py`, closing the
long-dead `serve.py` reference.

**Requirements:** R1, R2, R3, R4

**Dependencies:** None

**Files:**
- Create: `serve.py` (repo root, alongside `webui.py`)
- Test: `tests/test_webui_production_entrypoint.py`

**Approach:**
- `from webui import app` (do not call `create_app()` again).
- Top-level helper functions mirroring `webui.py`'s testable-helper
  convention (`_resolve_debug_mode`, `_resolve_bind_host`), e.g.
  `_resolve_threads() -> int` reading `WSGI_THREADS` (default `"1"`),
  raising `ValueError` for non-numeric or non-positive values rather than
  silently passing them to waitress (which never starts a worker thread
  when `threads<=0`, hanging every request).
- `if __name__ == '__main__':` block: disable the urllib3 insecure-request
  warning (parity with `webui.py`), call
  `_wire_content_fetch_ttl_from_env()`, resolve `PORT` (default 8888) and
  `bind_host` via the existing `_resolve_bind_host()`, force `app.debug =
  False`, print a startup banner that visually differs from the dev-server
  one (e.g. "Starting Backlink Publisher WebUI (production/waitress)..."),
  then `waitress.serve(app, host=bind_host, port=port,
  threads=_resolve_threads())`.
- When `_resolve_threads()` resolves above `1`, print a loud, unmissable
  startup warning naming the `webui_app/routes/drafts.py` bulk-publish-now
  single-flight gap before calling `waitress.serve(...)` — a warning, not a
  hard refusal, since raising thread count is a legitimate future choice
  once that gap is closed; this just makes the tradeoff visible at the
  moment of misconfiguration instead of only in source comments.

**Patterns to follow:**
- `webui.py:22-34,101-113` for the fail-safe helper-function style and
  `__main__` startup sequence.
- `webui_app/helpers/security.py::_resolve_bind_host` for how a
  startup-time env-driven resolver that raises on misconfiguration is
  written in this codebase.

**Test scenarios:**
- Happy path: `serve.py` module imports cleanly without executing the
  waitress server (guarded by `__main__`), and `serve.app is` the same
  object as `webui.app`.
- Happy path: `_resolve_threads()` returns `1` when `WSGI_THREADS` is unset.
- Edge case: `_resolve_threads()` returns the parsed int when
  `WSGI_THREADS` is set to a valid override (e.g. `"4"`).
- Error path: `_resolve_threads()` raises `ValueError` when `WSGI_THREADS`
  is `"0"`, negative, or non-numeric (code-review finding — waitress never
  starts a worker thread when `threads<=0`, which would silently hang every
  request forever; failing loudly at startup is strictly better than a
  silent hang).
- Edge case: a startup warning naming the `webui_app/routes/drafts.py` gap
  (the exact file, not just the substrings "drafts.py"/"bulk-publish-now",
  since the sibling `webui_app/api/v1/drafts.py` also matches those and is
  not the gap) is printed when `WSGI_THREADS` resolves above `1`, and is
  *not* printed when it resolves to `1` (default or explicit).
- Integration: the plan's core safety claim — that `threads=1` preserves
  the dev server's de facto request serialization, so the drafts.py
  bulk-publish-now gap stays latent — is asserted in Key Technical
  Decisions but was never verified by any test in earlier drafts of this
  plan (adversarial review finding). Add a test that starts `serve.py`'s
  `app` via `waitress.serve(..., threads=1)` in a background thread against
  an ephemeral port, fires two overlapping requests at a stub route with an
  artificial delay (or at the real bulk-publish-now route with a mocked
  slow `DraftAPI.bulk_publish_now`), and asserts the second request only
  begins processing after the first completes (observable via
  timestamps or an in-request counter), rather than running concurrently.
  This needs a real loopback socket, which the repo's autouse
  `_disable_real_network` fixture blocks by default (enforced by
  `pytest-socket`, with its own regression test,
  `test_environment_invariants.py::test_socket_block_is_armed`). Opt back in
  for this one test using the established pattern in
  `tests/e2e/publish_journey.py` — a fixture that calls
  `pytest_socket.enable_socket()`, requested only by this test, not applied
  file-wide.
- Happy path: the production entrypoint forces `app.debug = False` before
  serving, even when `FLASK_DEBUG=1` is set in the environment — this is a
  named Key Technical Decision (defense-in-depth against verbose
  tracebacks) and needs its own assertion so a later refactor of the
  `__main__` block can't silently drop it. Extract the debug-forcing line
  into a small testable helper (e.g. `_force_production_debug_off(app)`),
  matching the `_resolve_threads()` pattern, and assert `app.debug is
  False` after calling it on an app with `debug=True` pre-set.
- Integration: importing `serve` does not raise even though
  `_resolve_bind_host()` and `_wire_content_fetch_ttl_from_env()` are only
  invoked inside the `__main__` guard (i.e., import-time safety).
- Test expectation for the `__main__`-guarded waitress.serve() call itself:
  covered by the concurrency-serialization test above (which does start a
  real, ephemeral-port waitress instance in-process) — no separate
  process-lifecycle test is needed beyond that; manual verification still
  covers real process start/stop via the actual launchers (see Unit 3
  note).

**Verification:**
- `python -c "import serve"` succeeds with no side effects.
- The concurrency-serialization test passes, confirming `threads=1`
  preserves the dev server's request serialization.
- Manually running `python serve.py` on `127.0.0.1:8888` and hitting
  `/api/v1/health` returns 200, and the startup banner does not contain the
  Werkzeug dev-server warning text.
- Setting `WSGI_THREADS=4` and running `python serve.py` prints the
  drafts.py-gap warning before the server starts.

- [x] **Unit 2: Point the two canonical launchers at `serve.py`**

**Goal:** The git-tracked "one launcher per platform" scripts (AGENTS.md R9)
launch the production entrypoint instead of the dev server.

**Requirements:** R1, R3

**Dependencies:** Unit 1

**Files:**
- Modify: `scripts/launcher.command`
- Modify: `scripts/launcher.ps1`
- Modify: `tests/test_launcher_single_entry.py`
- Modify: `tests/test_launcher_ps1_encoding.py`

**Approach:**
- `scripts/launcher.command`: change `WEBUI_SCRIPT="${WEBUI_SCRIPT:-webui.py}"`
  default to `serve.py`. Existing env-override mechanism (used by the manual
  crash-stub test) is untouched.
- `scripts/launcher.ps1`: change the final `& $PY webui.py` line to `& $PY
  serve.py`.
- Verify the crash-restart-loop exit-code handling in `launcher.command`
  (`EXIT -eq 0 || EXIT -eq 130`, tied to how Werkzeug reports Ctrl-C) is
  still correct once the launched process is waitress, not Werkzeug — a
  graceful Ctrl-C must still exit 0/130 or the loop will misclassify a
  normal shutdown as a crash (see Risks & Dependencies).

**Patterns to follow:**
- The existing `WEBUI_SCRIPT` override mechanism already in
  `scripts/launcher.command`, designed for exactly this kind of swap.

**Test scenarios:**
- Happy path: extend `tests/test_launcher_single_entry.py` with an
  assertion that `scripts/launcher.command`'s body contains
  `WEBUI_SCRIPT:-serve.py}` (or equivalent), not `webui.py`, as the default.
- Happy path: extend `tests/test_launcher_ps1_encoding.py` (or add a
  sibling assertion) that `scripts/launcher.ps1`'s body contains `serve.py`
  as the final launch target.
- Regression: existing assertions in both files (single-`.command`-file
  count, BOM/encoding, `FLASK_DEBUG=0`/`SECRET_KEY`/`BACKLINK_PUBLISHER_LITE=1`
  pinning) continue to pass unmodified — this unit only changes the launch
  filename, nothing else in these scripts.

**Verification:**
- `pytest tests/test_launcher_single_entry.py tests/test_launcher_ps1_encoding.py`
  passes.
- Manual (macOS, deferred — see Risks & Dependencies): double-clicking
  `scripts/launcher.command` starts `serve.py`, the crash-restart loop still
  triggers correctly on an intentional crash and still recognizes a clean
  Ctrl-C exit.

- [x] **Unit 3: Point the workspace-root operator launchers at `serve.py`**

**Goal:** The actual files an operator double-clicks (or `make
restart-webui` invokes) run the production entrypoint — this is the code
path the user hit the dev-server warning through.

**Requirements:** R1, R3

**Dependencies:** Unit 1

**Files:**
- Modify (workspace root, outside this git repo — see note below):
  `start-webui.bat`, `启动WebUI.bat`, `restart_webui.bat`
- No change needed: `restart_webui.sh`, `启动WebUI.command` (both already
  invoke `serve.py` — verified directly: `启动WebUI.command` line 33 already
  reads `WEBUI_SCRIPT="${WEBUI_SCRIPT:-serve.py}"`)

**Approach:**
- These files live at the workspace root, not inside the
  `backlink-publisher/` git repo (confirmed: `test_exactly_one_command_launcher_in_repo`
  in `tests/test_launcher_single_entry.py` only globs inside the repo and
  passes today precisely because these are outside it). Editing them is a
  plain filesystem change, not a repo commit — call this out explicitly
  when the unit is done so the operator knows there's nothing to `git add`.
- `start-webui.bat`: change the final `"%PY%" webui.py` to `"%PY%"
  serve.py`.
- `启动WebUI.bat`: change the final `"%PYTHON_CMD%" webui.py` to
  `"%PYTHON_CMD%" serve.py`.
- `restart_webui.bat`: change the `start "BP-WebUI" /MIN cmd /c ""%PY%"
  webui.py > ..."` line to launch `serve.py`. Its process-kill matcher
  already matches both `*webui.py*` and `*serve.py*`, so no change needed
  there.
- `start-webui.bat` and `启动WebUI.bat`: their own stale-process cleanup
  step (a feature both advertise in their header comments) filters
  `CommandLine -like '*webui.py*'` only. Once their launch line points at
  `serve.py`, a leftover `serve.py` process from a prior run would escape
  this cleanup on the next double-click, falling through to the
  port-increment logic instead of reusing 8888 — quietly regressing the
  idempotent-restart behavior these scripts exist to provide. Extend both
  scripts' `Where-Object` filter from `$_.CommandLine -like '*webui.py*'`
  to `($_.CommandLine -like '*webui.py*' -or $_.CommandLine -like
  '*serve.py*')`, mirroring the dual-match pattern already used in
  `restart_webui.bat`.

**Patterns to follow:**
- `restart_webui.sh`'s existing `serve.py` invocation and
  `restart_webui.bat`'s existing dual-match kill regex — both already
  anticipate this exact rename.

**Test scenarios:**
- Test expectation: none — these files are outside the git repo and have no
  automated test harness (confirmed via repo-wide search: no test globs
  reach the workspace root). Verification is manual.
- Manual (Windows, this session's platform) — **done**: ran `start-webui.bat`
  end-to-end (with `serve.py` temporarily present in a copy of the target
  checkout, since this branch's `serve.py` doesn't exist on `main` until
  merged) — confirmed the waitress startup banner (no Werkzeug warning) and
  `curl http://127.0.0.1:8888/api/v1/health` returned 200.
- Manual (Windows) — **done**: ran `restart_webui.bat` the same way; exited
  0, log showed "Starting serve.py", health check returned 200.
- `启动WebUI.bat` edited identically to `start-webui.bat` (same two changes)
  but not separately executed end-to-end this session — parity assumed from
  the proven `start-webui.bat` run, not independently verified.
- Manual (macOS, deferred — no macOS access in this session): confirm
  `启动WebUI.command` (already correct, per Files above) still launches
  cleanly; flag as a follow-up manual check for whoever has macOS access.

**Verification:**
- Double-clicking `start-webui.bat` or `启动WebUI.bat` on this Windows
  machine no longer prints the Werkzeug "development server" warning.
- `restart_webui.bat` successfully cycles the process using `serve.py`.

- [x] **Unit 4: Update command references in docs**

**Goal:** Contributors reading the repo's own command docs see the
production entrypoint, not just the dev one.

**Requirements:** R1

**Dependencies:** Unit 1

**Files:**
- Modify: `backlink-publisher/AGENTS.md`
- Modify: `backlink-publisher/CLAUDE.md`

**Approach:**
- Both files currently list `python webui.py # :8888` under their
  respective "WebUI dev server" command bullets. Add an adjacent line for
  the production entrypoint, e.g. `python serve.py # :8888, waitress,
  production`, without removing or renaming the existing dev-server line
  (it remains valid for `FLASK_DEBUG=1` interactive use).

**Patterns to follow:**
- The existing terse, single-line command style already used in both
  files' command blocks.

**Test scenarios:**
- Test expectation: none — documentation-only change with no behavior to
  test.

**Verification:**
- Both files mention `serve.py` alongside the existing `webui.py` dev-server
  line, without altering any other command documented nearby.

## System-Wide Impact

- **Interaction graph:** Only the process-launch layer changes (which
  script/server invokes the already-existing `webui_app.create_app()`
  Flask app). No route, middleware, or store code is touched.
- **Error propagation:** Unchanged — same Flask app, same error handlers.
  Waitress surfaces unhandled exceptions as 500s the same way Werkzeug's
  non-debug mode does.
- **State lifecycle risks:** The one identified risk (drafts.py
  bulk-publish-now race) is neutralized by defaulting `threads=1` — see Key
  Technical Decisions. No other lazy-store or scheduler state is
  thread-count-sensitive today (APScheduler background jobs already run on
  their own thread regardless of the WSGI server's request-handling
  threads).
- **API surface parity:** None of the five launcher scripts this plan edits
  (two canonical in Unit 2, three workspace-root in Unit 3) differ in
  behavior after this change beyond which Python file they exec — same
  env vars, same port-scan/fallback logic, same SECRET_KEY persistence.
- **Integration coverage:** Covered by Unit 1's import-safety and
  concurrency-serialization tests (the latter opts back into real sockets
  for one test via the existing `tests/e2e/publish_journey.py` pattern,
  since the repo blocks real sockets by default) plus manual end-to-end
  launches in Units 2-3 (starting the actual launcher scripts and hitting
  `/api/v1/health`), since launcher-script behavior itself isn't something
  `pytest` can exercise.
- **Unchanged invariants:** `_resolve_bind_host()`'s loopback-only
  enforcement, `_resolve_debug_mode()`'s fail-safe default, CSRF/Origin
  checks, and the LITE-edition surface reduction are all untouched — this
  plan adds a new caller of the existing bind resolver, it does not modify
  the resolver.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Multi-threaded waitress could turn the known drafts.py bulk-publish-now single-flight gap into a live, exploitable race | Default `threads=1` in `serve.py`, verified by an automated concurrency test (Unit 1); a loud startup warning fires if `WSGI_THREADS>1` is ever set, naming the gap explicitly so the risk isn't silent even if someone overrides the default |
| `WSGI_THREADS<=0` would make waitress accept connections but never service them — a silent, total hang strictly worse than the race the default guards against (found in code review, verified against the vendored waitress 3.0.2 source) | `_resolve_threads()` now raises `ValueError` for any value below 1 or non-numeric, failing loudly at startup instead of hanging silently (Unit 1) |
| An earlier draft of `serve.py`'s `_DRAFTS_GAP_NOTE` (and this plan) cited `webui_app/api/v1/drafts.py` as the unlocked route; the actual unlocked route is `webui_app/routes/drafts.py` — `api/v1/drafts.py`'s own route already has a lock | Found and fixed in code review: corrected the file path in `serve.py`, strengthened the test assertion to check the exact path (not just the substrings "drafts.py"/"bulk-publish-now", which both files satisfy), and corrected this plan's references throughout |
| `scripts/launcher.command`'s crash-restart loop keys off Werkzeug's Ctrl-C exit codes (0 or 130); waitress may report a different exit code on SIGINT, causing a clean shutdown to be misclassified as a crash | Unresolved by live testing (Git Bash on Windows does not deliver POSIX SIGINT to a native Windows Python process reliably — the attempt hung; `scripts/launcher.command` only really runs on macOS/Linux anyway). Code review read waitress 3.0.2's own source (`waitress/server.py`): a `KeyboardInterrupt` is caught internally and `waitress.serve()` returns normally, so `serve.py` should exit 0 on a clean Ctrl-C, landing inside the launcher's accepted `{0, 130}` set — but this is source-level reasoning, not an empirical confirmation on the actual target platform. Remains a real, open verification gap for whoever next runs the launcher on macOS/Linux |
| Workspace-root launcher edits (Unit 3) are outside the git repo and have zero automated test coverage | Manual verification steps enumerated per-unit; flagged explicitly so the operator knows these changes won't show up in a PR diff |
| No macOS environment available in this session to verify `scripts/launcher.command` / `启动WebUI.command` end-to-end | Called out as a deferred manual check in Unit 3's test scenarios rather than silently assumed correct |
| `Dockerfile`/`docker-compose.yml` still reference `serve.py` with `BIND_HOST=0.0.0.0`, which will now find the file but immediately crash with `RuntimeError` from `_resolve_bind_host()` instead of `FileNotFoundError` | Explicitly out of scope (see Scope Boundaries); failure mode changes from "file not found" to "refused non-loopback bind," which is at least a clearer error, but full container support is deferred |

## Sources & References

- Related code: `webui.py`, `webui_app/helpers/security.py::_resolve_bind_host`,
  `webui_app/helpers/cli_runner.py::_wire_content_fetch_ttl_from_env`,
  `webui_app/routes/drafts.py` (the unlocked legacy route),
  `webui_app/api/v1/drafts.py:39-52` (documents the gap; its own `/api/v1`
  route already has the lock), `scripts/launcher.command`,
  `scripts/launcher.ps1`, `Dockerfile`, `docker-compose.yml`
- Related plans: `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`
  (confirms `serve.py` never existed), `docs/plans/2026-07-03-001-fix-windows-webui-encoding-crash-plan.md`
  (defers R9 launcher-consolidation and serve.py encoding hardening)
- `docs/solutions/ux-honesty/webui-false-success-resolution.md` — confirms
  the `webui_app/routes/drafts.py` bulk-publish-now split-state hazard
  independently (surfaced by `ce-learnings-researcher` during code review)
- `AGENTS.md` — "One launcher (R9)" convention
