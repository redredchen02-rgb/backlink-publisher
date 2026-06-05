---
title: "fix: notes.io migrated to AJAX /save endpoint — adapter publishes via dead form-POST path"
type: fix
status: completed
date: 2026-06-05
origin: dofollow-flip-assist backlog (notesio publish_failed canary verdict)
claims: {}
---

# fix: notes.io AJAX `short.php` endpoint migration

## Overview

`notesio` canary returns `ambiguous` / reason `publish_failed`. **Root cause is
not in our code paths' logic — it is an upstream contract change at notes.io.**
A 2026-06-05 read-only diagnostic (GET only, no publish) shows notes.io has
migrated from the server-rendered form-POST flow the adapter assumes to a
client-side AJAX submission. The current adapter therefore POSTs to a path that
no longer redirects, hits its own "no redirect" guard, and raises.

## Evidence (read-only diagnostic, 2026-06-05)

- `GET https://notes.io/` → HTTP 200, **no `Location` redirect**, Cloudflare in
  front (`cf-*` assets present; no challenge on GET).
- The homepage HTML **no longer contains** a `<form>` with `name="text"` /
  `name="token"` fields. Submission is JS-driven.
- `theme/scripts/notes.min.js` save handler (verbatim):
  ```js
  var e = "txt=" + encodeURIComponent($p_txt);
  $.ajax({ type: "POST", url: "short.php", data: e,
           success: function(e){ $("#sonuc").html(e) } });
  ```
  i.e. the live contract is now:
  - **endpoint**: `https://notes.io/short.php` (relative `short.php`)
  - **method**: POST, `application/x-www-form-urlencoded`
  - **single field**: `txt=<content>` (no `token` field)
  - **response**: an **HTML fragment** injected into `#sonuc` containing the
    published permalink — **not** a 30x redirect to the note URL.

## Problem Frame

`publishing/adapters/notesio_api.py` posts `{"text": body, "token": ""}` to
`_NOTESIO_ENDPOINT = "https://notes.io/"` and then asserts a redirect:

```python
submit_resp = submit_form(_NOTESIO_ENDPOINT, post_data)
published_url = (submit_resp.url or "").strip()
if not published_url or published_url == _NOTESIO_ENDPOINT:
    raise ExternalServiceError("notes.io did not redirect to a published URL after submit")
```

Against the new contract, `submit_resp.url` stays `https://notes.io/` (no
redirect), so the guard fires every time → `publish_failed`. The field name
(`text` vs `txt`) and endpoint (`/` vs `/save`→`short.php`) are also both stale.

This is the same failure class as the notesio brainstorm note: the adapter
encodes a platform contract that drifted.

## Requirements Trace

- R1. POST to the current endpoint (`https://notes.io/short.php`) with the
  current field (`txt=<body>`), not `/` with `{text, token}`.
- R2. Parse the published permalink out of the **HTML fragment response** (the
  `#sonuc` payload) instead of relying on a redirect on `submit_resp.url`.
- R3. Preserve the existing draft/published `AdapterResult` shape, the
  `attach_link_verification` call, and `post_publish_delay` behaviour.
- R4. Keep the SSRF / `submit_form` safety wrapper (no raw `requests`).
- R5. If the response fragment contains no parseable permalink, raise
  `ExternalServiceError` with the response prefix (so a future drift is loud,
  not a silent empty URL).

## Scope Boundaries

- Does **not** change the registry `dofollow=` flag for notesio — it stays
  `uncertain` until a real OUR-pipeline canary confirms the placed link's `rel`.
- Does **not** attempt to defeat Cloudflare. If the POST is challenged, that is a
  separate (browser-tier) concern; this plan covers the JSON/form contract only.
- Does **not** touch other anonymous adapters (txtfyi, telegraph).

## Why this is NOT shipped in the same pass as the canary/binding fixes

Verifying R2 (the exact `#sonuc` HTML shape and where the permalink lives in it)
**requires one real POST**, which creates a public note on notes.io — an
outward-facing side effect. The 2026-06-05 session was scoped to read-only
diagnosis + non-publishing code (canary retired-cohort gate, gitlabpages
binding). Implementing this fix should be paired with a single live canary run
(operator-consented) to pin the response parser against the real fragment, then
land R1–R5 together with that fixture captured as a regression test.

## Key Technical Decisions

- **Parse permalink from response body, not redirect.** The new flow returns
  200 + HTML; `submit_resp.url` is useless. Extract the first
  `https://notes.io/<slug>` (or relative `/<slug>`) anchor/href from the
  fragment. Capture a real fragment as a test fixture during the live canary so
  the regex/parse is grounded, not guessed.
- **Drop the `token` field.** The live contract sends only `txt`.

## Test Scenarios

- Happy path: given a captured real `short.php` HTML fragment fixture, the
  parser returns the correct `https://notes.io/<slug>` permalink.
- Error path: fragment with no permalink → `ExternalServiceError` (R5).
- Contract guard: a unit test asserting the adapter POSTs to `…/short.php` with
  a `txt` field (mock `submit_form`), so a future revert to `/`+`text` fails CI.

## Next Steps

→ `/ce:plan` deepen, then implement paired with one operator-consented live
  canary to capture the response fixture.
