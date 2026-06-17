# Catalog Adapter Operator Guide

How to add a new platform to the config-driven catalog, verify its dofollow
status, and contribute it back to the built-in directory.

---

## 1. YAML field reference

All valid keys are defined in `catalog_schema.py::VALID_TOP_LEVEL_KEYS`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `slug` | str | yes | Unique identifier; must not clash with existing `registered_platforms()` |
| `endpoint` | str | yes | Form-POST or API submit URL |
| `auth_type` | str | yes | `none` \| `api_key_header` \| `api_key_query` |
| `content_field` | str | yes | Form/JSON field name for article body |
| `csrf_prefetch` | bool | no | GET the form page first to extract CSRF tokens (default `false`) |
| `csrf_field_names` | list[str] | when csrf_prefetch=true | Hidden fields to extract |
| `permalink_via` | str | yes | `redirect` \| `json_path` \| `regex` |
| `permalink_arg` | str | when redirect: `Location`; when json_path: JSONPath; when regex: pattern | |
| `min_delay_s` | float | no | Seconds between publishes (default 0) |
| `dofollow` | bool\|str | yes | `true` \| `false` \| `uncertain` |
| `rationale` | str | when dofollow ≠ true | ≥ 80 stripped chars |
| `referral_value` | str | when dofollow ≠ true | `high` \| `low` |

The schema is the authoritative source — if this table diverges, trust the code.

---

## 2. None-auth form-POST (recommended starting point)

This is the simplest case: no login, no API key, just a form submit.

```yaml
myplatform:
  endpoint: https://example.com/submit
  auth_type: none
  content_field: body
  csrf_prefetch: false
  permalink_via: redirect
  permalink_arg: Location
  min_delay_s: 3.0
  dofollow: uncertain
  rationale: >
    [Your ≥80-char rationale explaining the dofollow signal and
    why it is uncertain pending a pipeline canary confirmation.]
  referral_value: low
```

**File location:** `src/backlink_publisher/publishing/adapters/catalog/myplatform.yaml`
The slug must match the YAML filename (without extension).

Run schema validation:
```bash
cd backlink-publisher
PYTHONPATH=src python -c "
from backlink_publisher.publishing.adapters.catalog.catalog_schema import load_entry
entry = load_entry('src/backlink_publisher/publishing/adapters/catalog/myplatform.yaml')
print('OK:', entry['slug'])
"
```

---

## 3. CSRF prefetch

For platforms that embed a CSRF token in the form page:

```yaml
myplatform:
  endpoint: https://example.com/new
  auth_type: none
  content_field: content
  csrf_prefetch: true
  csrf_field_names:
    - csrf_token
    - _token
  permalink_via: redirect
  permalink_arg: Location
  min_delay_s: 2.0
  dofollow: uncertain
  rationale: >
    [≥80-char rationale]
  referral_value: low
```

The adapter GETs `endpoint` first, extracts `input[name=csrf_token]` and
`input[name=_token]` from the HTML, then POSTs with those included.

---

## 4. Verifying dofollow status

After publishing a test post, verify the link attribute:

```bash
verify-dofollow myplatform
```

This reads the most recent publish queue entry for `myplatform`, fetches the
published page, and checks the `rel` attribute on the backlink.

- If confirmed dofollow → update `dofollow: true` in the YAML (drop `rationale`
  and `referral_value`), and re-run schema validation.
- If nofollow → set `dofollow: false`, update rationale.
- If uncertain (JS-rendered, etc.) → keep `dofollow: uncertain`, note in rationale.

The pipeline canary requirement: a platform only graduates to `dofollow=True`
in the confirmed list after an **our-pipeline** canary (not just a third-party
spot check). See `docs/solutions/dofollow-platform-shortlist.md`.

---

## 5. User override vs. built-in directory

**Built-in:** `src/backlink_publisher/publishing/adapters/catalog/` — committed
to the repo, available to all operators by default.

**User override:** `~/.config/backlink-publisher/catalog/` — personal overrides
that take precedence over built-in entries with the same slug. Use this for:
- Personal API keys embedded in YAML (not recommended — use env vars instead)
- Local testing before contributing back to built-in
- Overriding a built-in entry's `dofollow` verdict after your own canary

To check what is loaded (built-in + user):
```bash
PYTHONPATH=src python -c "
from backlink_publisher.publishing.adapters.catalog.catalog_schema import load_all_entries
from backlink_publisher.config import Config
cfg = Config.load()
for slug, entry in load_all_entries(cfg).items():
    print(slug, entry['dofollow'])
"
```

---

## 6. Dofollow gate rationale requirements

When `dofollow` is not `true`, both `rationale` and `referral_value` are required.

- `rationale`: ≥ 80 stripped characters. Explain the dofollow signal evidence,
  the uncertainty source, and what would flip the verdict.
- `referral_value`: `high` or `low`. Influences whether the platform is included
  in referral-only cohorts even without equity value.

Schema validation (`validate_entry`) enforces this at load time — an entry with
`dofollow: uncertain` and a short rationale will fail with `CatalogValidationError`
and the platform will not register.

---

## 7. Contributing a new built-in entry

1. Add `src/backlink_publisher/publishing/adapters/catalog/<slug>.yaml`
2. Run `PYTHONPATH=src pytest tests/test_adapter_catalog.py tests/test_adapter_catalog_registration.py` — confirm no regressions
3. Run `verify-dofollow <slug>` after a test publish — record the verdict
4. If `dofollow: true`: confirm via the pipeline canary before merging
5. Open a PR — the CI gate auto-registers the new entry via `register_catalog_entries()`
