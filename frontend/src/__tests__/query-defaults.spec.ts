/**
 * QueryClient defaultOptions guard — Plan 2026-07-06-005 W1 (D15).
 *
 * Before this unit `frontend/src/main.ts` constructed its `QueryClient` with
 * no `defaultOptions` at all, so every page silently inherited the library
 * defaults (`staleTime: 0`, `refetchOnWindowFocus: true`). That implicit
 * default was a common enabler of the Settings hydration-overwrite bug (W2)
 * and other refetch surprises — see
 * docs/audits/2026-07-06-webui-refresh-inventory.md for the full audit.
 *
 * This guard does two things, both via "read source text with regex" (same
 * technique as data-table-adoption.spec.ts — no DOM/browser needed):
 *
 * 1. Asserts `main.ts`'s `QueryClient` construction carries an explicit
 *    `defaultOptions` block, so a future edit can't silently delete it back
 *    to the implicit-default state.
 * 2. Asserts the known edit-surface Settings queries (the ones that hydrate
 *    a live editable form/textarea from `useQuery` data — audited in the
 *    inventory doc) explicitly set `refetchOnWindowFocus: false`, so
 *    switching tabs back to Settings never silently re-fires a fetch mid-edit.
 *
 * Red-path self-check performed during development (not committed): deleting
 * the `defaultOptions: { ... }` block from main.ts turns test 1 red; deleting
 * `refetchOnWindowFocus: false` from any one of the edit-surface queries below
 * turns test 2 red for that file. Both were verified locally before this file
 * was finalized.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
// __dir = .../backlink-publisher/frontend/src/__tests__
const SRC_DIR = resolve(__dir, '..')

function readSrc(rel: string): string {
  return readFileSync(resolve(SRC_DIR, rel), 'utf8')
}

describe('QueryClient defaultOptions guard', () => {
  it('main.ts constructs the QueryClient with an explicit defaultOptions block', () => {
    const text = readSrc('main.ts')

    // Find the `new QueryClient({ ... })` call and check `defaultOptions` is
    // a key inside it (not just present anywhere in the file, e.g. a comment).
    const ctorMatch = /new QueryClient\(\{([\s\S]*?)\n\}\)/.exec(text)
    expect(ctorMatch, 'expected to find `new QueryClient({ ... })` in main.ts').not.toBeNull()

    const ctorBody = ctorMatch![1]
    expect(ctorBody).toContain('defaultOptions')
    // The specific fields this unit decided on (D15) — both explicit, not
    // silently inherited from the library.
    expect(ctorBody).toMatch(/refetchOnWindowFocus:\s*true/)
    expect(ctorBody).toMatch(/staleTime:\s*30_000/)
  })

  it('Settings edit-surface queries explicitly disable window-focus refetch', () => {
    // Every Settings component whose useQuery data feeds a `watch(...)` that
    // hydrates an editable `reactive`/`ref` form field (audited by hand in
    // docs/audits/2026-07-06-webui-refresh-inventory.md). Read-only status
    // cards (MediumCard, VelogCard, ChannelsCard, SettingsSidebar,
    // ChannelBindingCard's overviewQuery) are NOT edit surfaces and correctly
    // inherit the site default instead.
    const EDIT_SURFACE_FILES = [
      'pages/Settings/SettingsPage.vue',
      'pages/Settings/BlogIdsCard.vue',
      'pages/Settings/BloggerCard.vue',
      'pages/Settings/ChannelBindingCard.vue',
      'pages/Settings/LlmSettingsCard.vue',
      'pages/Settings/NotionCard.vue',
    ]

    const missing: string[] = []
    for (const rel of EDIT_SURFACE_FILES) {
      const text = readSrc(rel)
      if (!/refetchOnWindowFocus:\s*false/.test(text)) {
        missing.push(rel)
      }
    }

    expect(
      missing,
      `\nexpected refetchOnWindowFocus: false in each edit-surface query:\n${missing.join('\n')}`,
    ).toEqual([])
  })
})
