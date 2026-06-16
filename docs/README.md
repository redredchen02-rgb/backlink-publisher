# docs/ — navigation index

Quick map of every subdirectory. Archive and generated artefacts are at the bottom.

## Active reference

| Directory | Purpose |
|---|---|
| `architecture/` | Architecture decision records and principle docs (4 files). Start here for the _why_ behind design choices. |
| `operations/` | Runbooks and setup guides for OAuth, geo probe, recheck, and login flows (4 files). |
| `runbooks/` | Step-by-step operator playbooks — canary closeout, publish saga, recheck deficit overlay (7 files). |
| `solutions/` | Committed lessons. Searchable by YAML frontmatter (`module`, `tags`, `problem_type`). Promoted via `/ce:compound`. Sub-categories: `best-practices/`, `architecture-patterns/`, `correctness/`, `developer-experience/`, `integration-issues/`, `logic-errors/`, `test-failures/`, `ui-bugs/`. |

## Working documents

| Directory | Purpose |
|---|---|
| `brainstorms/` | Live brainstorm drafts + `_drafts/` follow-up seeds (1 active file). |
| `ideation/` | Gate-first ideation queue and `gate-verdicts.md`. Superseded items live in `_archive/ideation/` (16 files). |
| `requirements/` | Requirements docs that feed into plans (1 file). |
| `plans/` | **Active plans live here.** Currently 2 active plans (v0.40 operator autonomy + docs consolidation). |
| `discovery/` | Discovery runs and canary pending state (2 files). |
| `notes/` | Misc operator notes and retired-platform write-ups (4 files). |
| `spike-notes/` | Short investigation notes from spikes (3 files). |
| `spikes/` | Full spike reports (4 files). |
| `audits/` | Recurring-trap eradication audits (1 file). |
| `diagnostics/` | Diagnostic artefacts (currently empty). |
| `phase0/` | Phase 0 indexation and velog spike reports (2 files). |

## Archive

| Directory | Purpose |
|---|---|
| `plans-archive/` | **Deprecated.** Only README.md remains. All archived plans are now in `_archive/plans/`. |
| `_archive/plans/` | All archived plans (167 files, dated 2026-05-11 through 2026-06-08). Consolidated from `plans-archive/` + original `_archive/plans/`. |
| `_archive/brainstorms/` | Completed / superseded brainstorm docs (91 files). |
| `_archive/ideation/` | Superseded ideation docs. |

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
