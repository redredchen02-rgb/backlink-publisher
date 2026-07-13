// frontend/src/__tests__/breakpoint-convention.spec.ts
// Split-screen breakpoint lock (app.css convention, Plan 2026-07-06-005 D12):
// every max-width media query in the SPA must use the 960px literal.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')

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
    for (const file of walk(SRC)) {
      const text = readFileSync(file, 'utf8')
      const queries = text.match(/@media[^{]*max-width:\s*(\d+)px/g) ?? []
      for (const q of queries) {
        const px = /max-width:\s*(\d+)px/.exec(q)?.[1]
        if (px !== '960') violations.push(`${file} — ${q.trim()}`)
      }
    }
    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })
})
