# Hashnode — Retired Platform

**Decision date:** 2026-07-06 (documentation catch-up; `visibility="retired"` has been live in the registry since PR #204)
**Status:** NO-GO — retired, adapter kept registered for explicit dispatch only

## Evidence

- Registered `dofollow="uncertain"` pending an OUR-pipeline canary. A 2026-05
  third-party live check found Hashnode post-body external `<a>` tags carry no
  `rel` attribute (= dofollow), but a third-party spot-check does not
  discharge the canary burden (livejournal/txtfyi precedent) — see
  `src/backlink_publisher/publishing/adapters/_nofollow_rationales.py`.
- Hashnode's GraphQL publish path hits a paywall — canary confirmation was
  never economically pursued past that gate.
- `canary-seed`/`canary-targets` exclude retired platforms automatically
  (`visibility="retired"` filter), so Hashnode does not appear in the evergreen
  monitoring cohort.

## Decision

Do not pursue a canary or flip to `dofollow=True`. `HashnodeGraphQLAdapter`
stays registered (`register("hashnode", ..., visibility="retired")`) so
`plan-backlinks --platform hashnode` remains available for explicit,
operator-directed dispatch, but it is excluded from all default seeding and
monitoring paths.

## If reconsidered

Require: a free (non-paywalled) publish path, a successful OUR-pipeline
canary, and `verify_link_attributes` confirmation of dofollow on the live
post before flipping `dofollow="uncertain"` → `True`.
