// Ported from webui_app/static/js/url_derive.js (Plan 2026-05-20-002 U4).
// Pure path-depth derivation; mirrors backlink_publisher._util.url_derive
// .derive_path_tiers 1:1 (same _CATEGORY_TOKEN regex, same branch structure).
// The DOM binding / verify orchestration from the original is NOT ported here —
// that becomes Vue components in a later unit; this is the pure kernel only.

export interface Tiers {
  main: string | null
  category: string | null
  work: string | null
}

// Letters only, 3-15 chars, no digits/hyphens. Hyphenated slugs are work URLs.
export const CATEGORY_TOKEN = /^[a-z]{3,15}$/i

export function derivePathTiers(rawUrl: unknown): Tiers {
  const none: Tiers = { main: null, category: null, work: null }
  if (typeof rawUrl !== 'string' || !rawUrl) return none

  let parsed: URL
  try {
    parsed = new URL(rawUrl)
  } catch {
    return none
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return none
  if (!parsed.host) return none

  // Normalize: scheme=https, drop query+fragment, trim trailing slash on
  // subpaths (keep root). Host preserved verbatim.
  const origin = 'https://' + parsed.host
  const segments = parsed.pathname.split('/').filter((s) => s !== '')

  const subpath = (segs: string[]): string => {
    const p = '/' + segs.join('/')
    return 'https://' + parsed.host + (p === '/' ? '' : p.replace(/\/+$/, ''))
  }

  if (segments.length === 0) return { main: origin, category: null, work: null }
  if (segments.length === 1) return { main: origin, category: subpath(segments), work: null }

  const tail = segments[segments.length - 1]
  if (CATEGORY_TOKEN.test(tail)) {
    return { main: origin, category: subpath(segments), work: null }
  }
  return {
    main: origin,
    category: subpath(segments.slice(0, -1)),
    work: subpath(segments),
  }
}
