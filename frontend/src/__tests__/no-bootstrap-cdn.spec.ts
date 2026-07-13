// Anti-rot guard (plan 2026-07-09-002 W4): the SPA must not depend on the
// Bootstrap CDN. The Vue SPA ships self-hosted design tokens + component CSS
// only; theme switching is driven by `data-theme` (theme store), not
// Bootstrap's `data-bs-theme`. A regression that re-adds the CDN link/script
// (or the dead `data-bs-theme` attribute) fails this test, surfacing the
// offline-breakage risk instead of letting it ship.
//
// `frontend/index.html` is the source of truth (spa_dist is regenerated from
// it on build); the built `spa_dist/index.html` is checked when present so a
// direct edit to the served bundle is also caught (tolerant when not built).
import { existsSync, readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const sourceHtml = resolve(here, '../../index.html')
const distHtml = resolve(here, '../../../webui_app/spa_dist/index.html')

const NO_BOOTSTRAP = /cdn\.jsdelivr\.net\/npm\/bootstrap/i
const NO_BS_THEME = /data-bs-theme/i

describe('SPA index.html has no Bootstrap CDN dependency', () => {
  it('source index.html has no bootstrap CDN / data-bs-theme', () => {
    const html = readFileSync(sourceHtml, 'utf-8')
    expect(html).not.toMatch(NO_BOOTSTRAP)
    expect(html).not.toMatch(NO_BS_THEME)
  })

  it('built spa_dist/index.html has no bootstrap CDN / data-bs-theme (when built)', () => {
    if (!existsSync(distHtml)) return // build artifact absent in some CI contexts
    const html = readFileSync(distHtml, 'utf-8')
    expect(html).not.toMatch(NO_BOOTSTRAP)
    expect(html).not.toMatch(NO_BS_THEME)
  })
})
