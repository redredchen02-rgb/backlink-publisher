---
status: pending
priority: p2
issue_id: "015"
tags: [security, hardening-sweep]
dependencies: []
---

# bind_channel.py's error handlers scrub stdout but still print unscrubbed exception text to stderr (currently inert, but a sibling module already reads subprocess stderr)

## Problem Statement

D3's fix to `cli/admin/bind_channel.py::main()` correctly scrubs the exception text going into the stdout `channel.bind.failed` JSONL event. However, the security code-review pass found the same handlers ALSO print the identical raw, unscrubbed exception text to stderr via `handle_error()`/`handle_unexpected_error()` (`src/backlink_publisher/_util/errors.py:250-269`). This is currently inert — `webui_app/services/bind_job.py::_drain_stdout()` never reads `proc.stderr` — but the sibling module `webui_app/services/keepalive_job.py` (lines 249-250) already does surface subprocess stderr into an operator-visible diagnostic, showing this is a plausible pattern a future change could reintroduce for bind jobs too, silently reopening the exact leak D3 was meant to close.

## Findings

- `src/backlink_publisher/cli/admin/bind_channel.py::main()`'s two catch-all arms scrub the stdout emit but not the stderr print path.
- `webui_app/services/bind_job.py::_drain_stdout()` confirmed to not read `proc.stderr` today — no live exposure.
- `webui_app/services/keepalive_job.py:249-250` confirmed to already read and surface subprocess stderr for a different job type — establishing this as a real, already-used pattern in this codebase, not a hypothetical.

## Proposed Solutions

### Option 1: Apply the same `scrub_text()` treatment to the stderr print path in `bind_channel.py::main()`'s catch-all handlers, for defense-in-depth parity with the stdout path

**Effort:** 30-60 minutes (small code change + a red-path test mirroring the existing stdout-scrub tests).
**Risk:** Low.

### Option 2: Leave as-is since it's currently inert; add a comment/debt-registry note documenting the latent risk so a future stderr-wiring change is forced to reconsider scrubbing

**Effort:** 15 minutes.
**Risk:** Low now, but relies on a future implementer reading the note.

## Recommended Action

**To be filled during triage.** Option 1 is cheap and closes the gap structurally rather than relying on a future reader noticing a comment — recommend applying it given how small the change is relative to the D3 unit's own stated goal.

## Technical Details

**Affected files:**
- `src/backlink_publisher/cli/admin/bind_channel.py::main()` (~lines 127-143)
- `src/backlink_publisher/_util/errors.py:250-269` (`handle_error`/`handle_unexpected_error`)
- `webui_app/services/bind_job.py` (confirms current non-exposure)
- `webui_app/services/keepalive_job.py:249-250` (the sibling pattern that makes this a live risk, not theoretical)

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (security reviewer), 2026-07-06.
- Related commit: `c104dd95` (D3).

## Acceptance Criteria

- [ ] Exception text printed to stderr by `bind_channel.py::main()`'s catch-all handlers is scrubbed identically to the stdout path (or a documented decision explains why stderr is treated differently).
- [ ] A test proves scrubbing applies to both output channels.

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review security persona)

**Actions:**
- Traced the full stderr path from `handle_error`/`handle_unexpected_error` and confirmed `bind_job.py` doesn't currently read it.
- Found the `keepalive_job.py` precedent that reads subprocess stderr for a different job type, establishing this as a realistic future risk.

---

## Notes

- Currently zero live exposure — flagged as a P2 (moderate, meaningful downside) precisely because the risk is latent rather than active today.
