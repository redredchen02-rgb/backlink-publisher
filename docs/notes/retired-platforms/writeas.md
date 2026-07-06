# write.as — Retired Platform

**Decision date:** 2026-07-06 (documentation catch-up; `visibility="retired"` has been live in the registry since PR #202)
**Status:** NO-GO — retired, adapter kept registered for explicit dispatch only

## Evidence

- Registered `dofollow="uncertain"` pending an OUR-pipeline canary. A 2026-05
  third-party live check found write.as post-body external `<a>` tags
  (including embeds) carry no `rel` attribute (= dofollow), but a third-party
  spot-check does not discharge the canary burden (livejournal/txtfyi
  precedent) — see
  `src/backlink_publisher/publishing/adapters/_nofollow_rationales.py`.
- `referral_value="low"`: minimalist, low-DA blogging host — retirement was
  judged low-cost relative to the pending canary burden.
- `canary-seed`/`canary-targets` exclude retired platforms automatically
  (`visibility="retired"` filter), so write.as does not appear in the
  evergreen monitoring cohort.

## Decision

Do not pursue a canary or flip to `dofollow=True`. `WriteasAPIAdapter` stays
registered (`register("writeas", ..., visibility="retired")`) so
`plan-backlinks --platform writeas` remains available for explicit,
operator-directed dispatch, but it is excluded from all default seeding and
monitoring paths.

## If reconsidered

Require: a successful OUR-pipeline canary and `verify_link_attributes`
confirmation of dofollow on the live post before flipping
`dofollow="uncertain"` → `True`.
