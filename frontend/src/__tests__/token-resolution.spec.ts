/**
 * Token drift guard — ensures every var(--name) in the Vue SPA resolves to a
 * name defined in tokens.css, and that no literal colour fallbacks remain.
 *
 * Bans:  var(--x, #hex)  var(--x, rgb...)  — literal colour fallbacks mask drift
 * Allows: var(--x, var(--y)) — token-chain fallback is valid CSS
 * Allows: var(--x) — no fallback
 *
 * Placed in frontend.yml vitest lane (triggers on frontend/** + webui_app/static/css/**)
 * so any future drift breaks CI before it ships.
 */

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { resolve, join, dirname, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
// __dir = .../backlink-publisher/frontend/src/__tests__
const TOKENS_CSS = resolve(__dir, '../../../webui_app/static/css/tokens.css')
const SPA_SRC    = resolve(__dir, '..')   // .../frontend/src

// ── helpers ──────────────────────────────────────────────────────────────────

function definedTokens(css: string): Set<string> {
  const names = new Set<string>()
  for (const m of css.matchAll(/--([\w-]+)\s*:/g)) names.add(`--${m[1]}`)
  return names
}

function walkFiles(dir: string, exts: Set<string>): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      out.push(...walkFiles(full, exts))
    } else if (exts.has(extname(entry))) {
      out.push(full)
    }
  }
  return out
}

/** Extract CSS text: for .vue files, join all <style> block contents. */
function cssOf(file: string): string {
  const raw = readFileSync(file, 'utf8')
  if (!file.endsWith('.vue')) return raw
  return [...raw.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)]
    .map(m => m[1])
    .join('\n')
}

function relPath(abs: string): string {
  return abs.replace(resolve(__dir, '../../../../') + '/', '')
}

// ── fixtures ─────────────────────────────────────────────────────────────────

const tokensCss  = readFileSync(TOKENS_CSS, 'utf8')
const defined    = definedTokens(tokensCss)
const spaFiles   = walkFiles(SPA_SRC, new Set(['.vue', '.css']))

// ── tests ─────────────────────────────────────────────────────────────────────

describe('token-resolution guard', () => {
  it('every var(--name) in frontend/src resolves to a tokens.css defined name', () => {
    const violations: string[] = []

    for (const file of spaFiles) {
      const css = cssOf(file)
      const rel = relPath(file)
      const lines = css.split('\n')

      lines.forEach((line, i) => {
        for (const m of line.matchAll(/var\(\s*(--[\w-]+)/g)) {
          const token = m[1]
          if (!defined.has(token)) {
            violations.push(`${rel}:${i + 1} — undefined token ${token}`)
          }
        }
      })
    }

    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })

  it('no var(--name, #hex|rgb) literal colour fallbacks in frontend/src', () => {
    // Bans literal colour values as the second argument to var().
    // var(--x, var(--y)) token-chain fallbacks are explicitly allowed.
    const LITERAL_COLOUR_FALLBACK = /var\(--[\w-]+\s*,\s*(#|rgba?|hsla?)/

    const violations: string[] = []

    for (const file of spaFiles) {
      const css = cssOf(file)
      const rel = relPath(file)
      const lines = css.split('\n')

      lines.forEach((line, i) => {
        if (LITERAL_COLOUR_FALLBACK.test(line)) {
          violations.push(`${rel}:${i + 1} — literal colour fallback: ${line.trim()}`)
        }
      })
    }

    expect(violations, `\n${violations.join('\n')}`).toEqual([])
  })
})
