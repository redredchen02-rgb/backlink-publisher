// frontend/src/__tests__/breakpoint-convention.spec.ts
// Split-screen breakpoint lock (app.css convention, Plan 2026-07-06-005 D12):
// every max-width media query in page-level styles must use the 960px
// literal.
//
// Scope is deliberately src/pages + src/styles, NOT all of src. The 960px
// rule is the split-screen PAGE convention; it does not apply to
// src/layout/*. The app shell (AppShell.vue/SideNav.vue/TopBar.vue) uses its
// own, older 1024px breakpoint on purpose: SideNav's drawer collapse
// deliberately mirrors the legacy drawer breakpoint at
// webui_app/static/css/global_nav.css:268 (`@media (max-width: 1024px)`), and
// changing it would alter sidebar collapse behaviour in the 960-1024px range
// and break legacy parity. This exemption is temporary — Phase B retires the
// legacy shell, at which point src/layout/* can be revisited and folded into
// (or reconciled with) this same 960px convention.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const SCAN_DIRS = ['pages', 'styles'].map((d) => join(ROOT, d))

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) yield* walk(p)
    else if (/\.(vue|css)$/.test(name)) yield p
  }
}

describe('breakpoint convention', () => {
  it('all max-width media queries use the 960px split-screen literal', () => {
    const violations: string[] = []
    for (const dir of SCAN_DIRS) {
      for (const file of walk(dir)) {
        const text = readFileSync(file, 'utf8')
        const queries = text.match(/@media[^{]*max-width:\s*(\d+)px/g) ?? []
        for (const q of queries) {
          const px = /max-width:\s*(\d+)px/.exec(q)?.[1]
          if (px !== '960') violations.push(`${file} — ${q.trim()}`)
        }
      }
    }
    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })
})
