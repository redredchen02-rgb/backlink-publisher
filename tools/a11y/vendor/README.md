# Vendored axe-core

`axe.min.js` is the [axe-core](https://github.com/dequelabs/axe-core)
accessibility engine, vendored (committed) on purpose.

This repo's frontend is intentionally **zero-build, no Node/bundler**
(see `CLAUDE.md`). Committing the single minified file lets `make test-a11y`
run a real, hermetic, offline audit — no `npm install`, no CDN fetch at test
time — by injecting it into a headless Chromium via
`tools/a11y/audit.py` (`page.add_script_tag`).

| | |
|---|---|
| Version | **4.10.2** (pinned) |
| Source | `https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js` |
| License | Mozilla Public License 2.0 (header retained in the file) |

## Updating

```bash
curl -fsSL "https://cdn.jsdelivr.net/npm/axe-core@<VERSION>/axe.min.js" \
  -o tools/a11y/vendor/axe.min.js
```

Then bump the version in this README and re-run `make test-a11y` to confirm the
rule set still passes (a new axe version can add or retune rules).
