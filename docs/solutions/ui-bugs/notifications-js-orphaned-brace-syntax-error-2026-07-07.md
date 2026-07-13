---
title: Orphaned brace in notifications.js broke UI on every legacy Jinja page
date: 2026-07-07
category: docs/solutions/ui-bugs
module: webui_app/static/js/notifications
problem_type: ui_bug
component: frontend_stimulus
symptoms:
  - "SyntaxError: Unexpected token '}' thrown when notifications.js ES module parses, aborting the entire module"
  - "Notification bell non-functional on all un-migrated legacy Jinja pages (/, /ce:history, /sites, /batch-campaign)"
  - "Toast rendering silently broken for flash messages and captured errors"
  - "Error-report-entry wiring absent on affected pages"
root_cause: logic_error
resolution_type: code_fix
severity: high
related_components:
  - webui_app/templates/base.html
  - webui_app/static/js/lib/dom.js
tags: [es-modules, syntax-error, refactor-leftover, legacy-jinja-frontend, silent-failure, ci-gap]
---

# Orphaned brace in notifications.js broke UI on every legacy Jinja page

> Note on `component:` — the schema's component enum (`rails_model`, `frontend_stimulus`, `hotwire_turbo`, etc.) was written for a Rails/Hotwire stack and has no exact match for this repo's legacy Flask + Jinja + vanilla-ES-module frontend. `frontend_stimulus` was chosen as the closest analog (the enum's only "classic/legacy frontend JS" bucket); treat it as an approximation, not a precise fit.

## Problem

On legacy Jinja pages (`/`, `/ce:history`, `/sites`, `/batch-campaign`, and every other non-SPA page), the notification bell, toast rendering (flash messages and captured-error toasts), and error-report-entry wiring were silently dead for about 8 days. Users only noticed indirectly as "other pages seem unreachable" (其他頁面好像會連不上), even though the backend was serving every route correctly.

## Symptoms

- Browser console on every legacy page load: `SyntaxError: Unexpected token '}'` thrown from `webui_app/static/js/notifications.js`.
- Confirmed live (via browser automation) on `/`, `/ce:history`, `/sites`, `/batch-campaign`.
- Notification bell did not update, toasts (flash messages, captured-error toasts) never rendered, and `ui/error-report-entry.js` wiring (loaded after `notifications.js` in `base.html`'s module script sequence) never ran.
- Vue 3 SPA pages under `/app/*` were completely unaffected — they don't load `base.html` or this script; verified via HTTP probing all ~13 migrated SPA routes (200/expected-302) plus live browser checks showing zero console errors.

## What Didn't Work

- **Suspected the WebUI launcher scripts** (`serve.py` vs `webui.py` entrypoint mismatch, deprecated `wmic`/`timeout.exe` calls) as the cause. This was a real, separate, already-fixed issue, but ruled out as the cause here: HTTP-level probing of the Flask route map (~212 registered routes) showed the backend was serving every route correctly. The break was purely a client-side JS parse error affecting only the legacy (non-SPA) page family — a server/launcher issue would have shown up as failed requests, not console errors on successfully-loaded pages.
- **A same-day sibling plan doc**, `docs/plans/2026-07-07-002-fix-production-wsgi-entrypoint-plan.md`, describing an intentional planned swap of the dev server for a production `waitress`-based `serve.py` entrypoint, was found during investigation and initially looked related given the timing. It's unrelated, unimplemented work and was not conflated with this bug.

## Solution

Root cause traced via `git log -p -L 10,20:webui_app/static/js/notifications.js` to commit `2c749b0f` (2026-06-30, "perf(optimization): comprehensive round 1+2 optimization"), which deduplicated a local `el()` helper into `webui_app/static/js/lib/dom.js` but left an orphan closing brace behind.

Before (broken):
```js
export const NOTIFY_EVENT = 'app:notify';

// el() is imported from ./lib/dom.js — shared across all page modules.
}

/**
```

After (fixed, `85a9e1a7`):
```js
export const NOTIFY_EVENT = 'app:notify';

// el() is imported from ./lib/dom.js — shared across all page modules.

/**
```

Fix was deleting the single stray `}` line. Verified via `node --check webui_app/static/js/notifications.js` (syntax OK) and live browser re-checks on all 4 previously-broken pages (zero console errors post-fix).

## Why This Works

The commit removed the body of `function el(tag, props = {}, children = []) { ... return node; }` and replaced it with a one-line comment, since `el()` was already imported from `./lib/dom.js` at the top of the file (`import { on, qs, qsa, el } from './lib/dom.js';`, line 5). But the function's *own* closing `}` sat on a line the diff hunk treated as unchanged context (it wasn't part of the deleted block boundary as the author selected it), so it wasn't removed along with the rest of the function body — leaving a `}` with no matching `{` anywhere above it in the file.

Because `notifications.js` is loaded as `<script type="module" src="...">` in `webui_app/templates/base.html`, this orphan brace produced a top-level `SyntaxError` during module parsing. Per the ES module spec, a module that fails to parse never executes at all — not even the parts before the error. So every export and side effect in the file (the notify-event wiring, toast rendering, bell updates) was dead on arrival on every page that loaded `base.html`, with no partial functionality and no server-side signal that anything was wrong.

## Prevention

There is no CI/test step that actually parses the shipped JS assets under `webui_app/static/js/` the way `base.html` loads them. The repo has `node:test` coverage for `notifications.js`'s *logic*, but that doesn't catch a flat top-level syntax error in the file as shipped — which is exactly why this went undetected for over a week. This is a **recurring gap**: prior commits (`f6ee0287`, `06d13b32`, `7f421c0c`, `f5d83845`, `d7de20ac`) also touched `notifications.js`/toast wiring without ever being documented as a solutions doc, and none of that history caught this class of regression.

Recommended guardrail: add a fast CI parse-check over every module script referenced by `base.html`, e.g.:

```bash
node --check webui_app/static/js/**/*.js
```

or, for stronger coverage of actual import graphs (catching missing files/exports too), a dry-parse/bundle step such as `esbuild webui_app/static/js/notifications.js --bundle --outfile=/dev/null` run for each entry script listed in `base.html`. This should run as a cheap pre-merge CI gate alongside the existing `py_compile`/`ast.parse`/`ruff` checks, since it's the client-side equivalent of "does this file even parse."

## Related Issues

- No related `docs/solutions/` doc exists — searched frontmatter and full text for notifications.js/toast/dom.js/el()/SyntaxError/ES-module/2c749b0f/dual-frontend keywords; only low-overlap false positives found (unrelated Python drift-check and pytest-marker docs matched on incidental substrings). `docs/solutions/best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md` is webui-frontend-adjacent but concerns Jinja template structure, not JS module wiring (overlap: low-moderate, 1/5 dimensions).
- No related GitHub issues (`gh issue list --search "notifications.js OR el() helper OR SyntaxError" --state all` returned zero results).
- Related commit: `2c749b0f` (root cause, 2026-06-30). Fix commit: `85a9e1a7` (2026-07-07).
