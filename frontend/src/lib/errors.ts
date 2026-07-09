// Ported from webui_app/static/js/ui/errors.js (Plan 2026-06-18-001 U4 / R4).
// Single error taxonomy: maps any failure onto a finite category with a FIXED
// title + message. Raw server/exception text is NEVER spliced into the
// user-facing strings (XSS boundary); `detail` is sanitized for diagnostics only.

export const CATEGORIES = ['network', 'permission', 'server', 'unknown'] as const
export type Category = (typeof CATEGORIES)[number]

export interface Classified {
  category: Category
  title: string
  message: string
  retryable: boolean
  status: number | null
  detail: string
  // Per-row / structured error details when the server provides them (e.g.
  // validate-backlinks row failures). Surfaced so the operator can see *what*
  // failed instead of only a summary count. Absent when the server sends none.
  errors?: string[]
}

const TEMPLATES: Record<Category, { title: string; message: string; retryable: boolean }> = {
  network: { title: '网络连接失败', message: '无法连接服务器，请检查网络后重试。', retryable: true },
  permission: { title: '权限或会话已过期', message: '登录状态或安全令牌已失效，请刷新页面后重试。', retryable: true },
  server: { title: '服务器出错了', message: '服务暂时不可用，请稍后重试。', retryable: true },
  unknown: { title: '出错了', message: '发生未知错误，请重试。', retryable: true },
}

// Strip ASCII control chars + DEL, then collapse whitespace, then length-cap, so
// a hostile body cannot garble the UI. Mirrors errors.js _detail() (which used
// \x00-\x1f); \x escapes keep the source free of literal control bytes.
const CONTROL_CHARS = /[\x00-\x1f\x7f]+/g

function detailOf(raw: unknown): string {
  if (raw == null) return ''
  let s = String(raw).replace(CONTROL_CHARS, ' ').replace(/\s+/g, ' ').trim()
  if (s.length > 140) s = s.slice(0, 137) + '…'
  return s
}

function statusOf(x: unknown): number | null {
  if (x != null && typeof x === 'object') {
    const obj = x as Record<string, unknown>
    if (obj.status != null) {
      const s = Number(obj.status)
      if (Number.isFinite(s) && s > 0) return s
    }
    const m = /HTTP\s+(\d{3})/.exec(String(obj.message ?? ''))
    return m ? Number(m[1]) : null
  }
  const m = /HTTP\s+(\d{3})/.exec(String(x ?? ''))
  return m ? Number(m[1]) : null
}

// Pull a flat list of per-row error strings out of an RFC 9457 problem+json
// `errors` array (each entry is `{"detail": "…"}` or a bare string). Sanitized
// like detailOf (control-char strip + collapse) since the text can embed
// untrusted content (target URLs / fetched snippets). Returns undefined when the
// server sent nothing structured — callers must not rely on it being present.
function errorsOf(x: unknown): string[] | undefined {
  const obj = x as Record<string, unknown> | null
  const raw = obj && typeof obj === 'object' ? obj.errors : null
  if (!Array.isArray(raw) || raw.length === 0) return undefined
  const out: string[] = []
  for (const item of raw) {
    if (item == null) continue
    const s =
      typeof item === 'string'
        ? item
        : typeof item === 'object' && 'detail' in (item as Record<string, unknown>)
          ? String((item as Record<string, unknown>).detail)
          : String(item)
    const cleaned = s.replace(CONTROL_CHARS, ' ').replace(/\s+/g, ' ').trim()
    if (cleaned) out.push(cleaned)
  }
  return out.length ? out : undefined
}

export function classifyError(input: unknown): Classified {
  let category: Category = 'unknown'
  const status = statusOf(input)
  const msg = String((input as { message?: string })?.message ?? '')
  const isNetwork =
    input instanceof TypeError ||
    (input as { name?: string })?.name === 'TypeError' ||
    /failed to fetch|networkerror|无法连接|连接服务器/i.test(msg)

  if (status != null) {
    if (status === 401 || status === 403 || status === 419) category = 'permission'
    else if (status >= 500 && status <= 599) category = 'server'
    else category = 'unknown'
  } else if (isNetwork) {
    category = 'network'
  }

  const tpl = TEMPLATES[category]
  const obj = input as Record<string, unknown> | null
  const rawDetail =
    (obj && typeof obj === 'object' && 'error' in obj ? obj.error : null) ?? msg ?? ''
  // ApiError keeps the server body on `.payload`; structured `errors` live there
  // (not directly on the instance). Fall back to a plain object with `.errors`.
  const payloadObj =
    obj && typeof obj === 'object' && 'payload' in obj && obj.payload && typeof obj.payload === 'object'
      ? (obj.payload as Record<string, unknown>)
      : obj
  return {
    category,
    title: tpl.title,
    message: tpl.message,
    retryable: tpl.retryable,
    status,
    detail: detailOf(rawDetail),
    errors: errorsOf(payloadObj),
  }
}
