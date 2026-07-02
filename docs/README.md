# docs/ — navigation index

Quick map of every subdirectory. Archive and generated artefacts are at the bottom.

## Active reference

| Directory | Purpose |
|---|---|
| `architecture/` | Architecture decision records and principle docs. Start here for the _why_ behind design choices. |
| `operations/` | Runbooks and setup guides for OAuth, geo probe, recheck, and login flows. |
| `runbooks/` | Step-by-step operator playbooks — canary closeout, publish saga, recheck deficit overlay. |
| `solutions/` | Committed lessons. Searchable by YAML frontmatter (`module`, `tags`, `problem_type`). Promoted via `/ce:compound`. Sub-categories: `best-practices/`, `architecture-patterns/`, `correctness/`, `developer-experience/`, `integration-issues/`, `logic-errors/`, `test-failures/`, `ui-bugs/`. |

## Working documents

| Directory | Purpose |
|---|---|
| `brainstorms/` | Live brainstorm/requirements docs feeding active or recently-shipped plans; `_drafts/` is a holding pen for not-yet-activated followup templates. |
| `ideation/` | Gate-first ideation queue. `gate-verdicts.md` is a **live, code-enforced ledger** (see `tests/test_gate_verdicts_ledger.py`, `src/backlink_publisher/gates/`) — never archive it. Superseded items live in `_archive/ideation/`. |
| `requirements/` | Requirements docs that feed into plans. |
| `plans/` | **Active plans live here.** Check each file's `status:` frontmatter (`active` / `completed` / `shipped` / `parked`) — do not trust a stale count in this table; grep for `^status:\s*active` instead. |
| `discovery/` | Discovery runs and canary pending state. `canary-pending.md` is test-enforced (`tests/test_canary_pending_deadline.py`) — never archive it. |
| `notes/` | Misc operator notes and retired-platform write-ups. `channel-decisions.json` and `retired-platforms/*` are loaded at runtime by `src/backlink_publisher/channel_discovery/decided.py` — never archive them. |
| `spike-notes/` | Short investigation notes from spikes; some are load-bearing (linked from live runbooks/code/active plans) even after the spike itself closed. |
| `spikes/` | Full spike write-ups (closed spikes archived to `_archive/spikes/`). Also a gitignored output target for `make scaffold` (see repo root `README.md`) — kept via `.gitkeep` even when empty of tracked spike docs. |
| `audits/` | One-time audit reports, intentionally kept as frozen historical records (not superseded, not stale). |
| `diagnostics/` | Diagnostic artefacts (gitignored output target for `make diagnose`; currently empty except `.gitkeep`). |
| `phase0/` | Phase 0 indexation and velog spike reports. |

## Archive

| Directory | Purpose |
|---|---|
| `plans-archive/` | **Deprecated.** Only README.md remains. All archived plans are now in `_archive/plans/`. |
| `_archive/plans/` | All archived plans. Consolidated from `plans-archive/` + original `_archive/plans/`. |
| `_archive/brainstorms/` | Completed / superseded brainstorm docs, including a `_drafts/` subfolder for archived followup templates. |
| `_archive/ideation/` | Superseded ideation docs. |
| `_archive/spikes/`, `_archive/spike-notes/` | Closed spike write-ups and progress notes, plus the raw Velog recon fixtures they depended on. |
| `_archive/requirements/`, `_archive/runbooks/` | Superseded requirements docs and one-off closed-out runbooks. |
| `_archive/` (root files) | Superseded root-level reports, e.g. the 4 optimization reports consolidated into `docs/optimization-history.md`. |

## Finding a plan

```bash
# Open work (status: active)
python3 -c "
import re, pathlib
for p in sorted(pathlib.Path('docs/plans').glob('*.md')):
    m = re.search(r'^status:\s*(\S+)', p.read_text(), re.MULTILINE)
    if m and m.group(1) == 'active':
        print(p.name)
"

# Search by keyword across all plans (active + archive)
grep -r "KEYWORD" docs/plans/ docs/plans-archive/ docs/_archive/plans/ -l
```

## Finding a solution doc

```bash
# By module
grep -r "module: anchor" docs/solutions/ -l

# By tag
grep -r "tags:.*csrf" docs/solutions/ -l
```
