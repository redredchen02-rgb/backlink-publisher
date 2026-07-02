import { describe, expect, it } from 'vitest'
import { derivePathTiers } from './urlDerive'

describe('derivePathTiers', () => {
  it('root URL -> main only', () => {
    expect(derivePathTiers('https://example.com')).toEqual({
      main: 'https://example.com',
      category: null,
      work: null,
    })
  })

  it('single segment -> main + category', () => {
    const t = derivePathTiers('https://example.com/blog')
    expect(t.main).toBe('https://example.com')
    expect(t.category).toBe('https://example.com/blog')
    expect(t.work).toBeNull()
  })

  it('letters-only tail token -> treated as category landing', () => {
    const t = derivePathTiers('https://example.com/blog/tech')
    expect(t.category).toBe('https://example.com/blog/tech')
    expect(t.work).toBeNull()
  })

  it('hyphenated slug tail -> work URL', () => {
    const t = derivePathTiers('https://example.com/blog/my-first-post')
    expect(t.category).toBe('https://example.com/blog')
    expect(t.work).toBe('https://example.com/blog/my-first-post')
  })

  it('normalizes scheme to https and drops query/fragment', () => {
    const t = derivePathTiers('http://example.com/a/post-1?x=1#frag')
    expect(t.main).toBe('https://example.com')
    expect(t.work).toBe('https://example.com/a/post-1')
  })

  it('invalid / non-http -> all null', () => {
    expect(derivePathTiers('not a url')).toEqual({ main: null, category: null, work: null })
    expect(derivePathTiers('ftp://example.com/x')).toEqual({ main: null, category: null, work: null })
    expect(derivePathTiers('')).toEqual({ main: null, category: null, work: null })
  })
})
