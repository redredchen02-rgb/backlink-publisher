/**
 * ui/errors.js — shared error taxonomy (Plan 2026-06-18-001 U4 / R4).
 *
 * classifyError(errOrResponse) maps any failure — a thrown Error/TypeError, a
 * fetch Response, or a {ok:false, status?, error?} JSON payload — onto a FINITE
 * category set, each with a FIXED title + message template. This is the single
 * source the core-flow renderError call-sites read, so "出错了" reads the same on
 * every page (monitor_hub, index, settings, …).
 *
 * SECURITY: the title/message come ONLY from the fixed templates below — raw
 * server/exception text is never spliced into them. classify() extracts a short,
 * sanitized `detail` (control chars stripped, length-capped) that the CALLER may
 * pass to renderError({message}) verbatim; renderError routes it through
 * textContent (never innerHTML), so even that detail cannot inject markup. Most
 * call-sites should prefer the category `message` and keep `detail` for diagnostics.
 *
 * Boundary rule (toast vs inline): transient ACTION feedback (a click/submit that
 * succeeded or failed) → toast via notifications.js; a REGION/list load failure →
 * inline renderError(onRetry) built from this taxonomy.
 */

// CATEGORIES — the finite set. Order is not significant; lookups are by key.
export const CATEGORIES = ['network', 'permission', 'server', 'unknown'];

// Fixed templates. title + message are the ONLY user-facing strings; they never
// interpolate server text. retryable hints the affordance the caller wires.
const TEMPLATES = {
    network: {
        title: '网络连接失败',
        message: '无法连接服务器，请检查网络后重试。',
        retryable: true,
    },
    permission: {
        title: '权限或会话已过期',
        message: '登录状态或安全令牌已失效，请刷新页面后重试。',
        retryable: true,
    },
    server: {
        title: '服务器出错了',
        message: '服务暂时不可用，请稍后重试。',
        retryable: true,
    },
    unknown: {
        title: '出错了',
        message: '发生未知错误，请重试。',
        retryable: true,
    },
};

// _detail() — derive a short, safe diagnostic string. NEVER feeds the title/
// message; only offered as an optional appendix the caller may surface. Collapses
// whitespace + control chars, then caps length so a hostile body cannot garble UI.
function _detail(raw) {
    if (raw == null) return '';
    let s = String(raw);
    // eslint-disable-next-line no-control-regex
    s = s.replace(/[\u0000-\u001f\s]+/g, ' ').trim();
    if (s.length > 140) s = s.slice(0, 137) + '…';
    return s;
}

// _statusOf() — pull an HTTP status from a Response / payload / Error-with-status,
// or parse a trailing "HTTP <code>" that fetchJson bakes into its thrown message.
function _statusOf(x) {
    if (x == null) return null;
    // Coerce: a backend may send {status: "500"} (string) — Number() catches both.
    if (x.status != null) {
        const s = Number(x.status);
        if (Number.isFinite(s) && s > 0) return s;
    }
    const msg = (x && x.message) || '';
    const m = /HTTP\s+(\d{3})/.exec(String(msg));
    return m ? Number(m[1]) : null;
}

/**
 * classifyError — map a failure onto {category, title, message, retryable, status, detail}.
 *
 * Inputs handled:
 *   - a TypeError / network "Failed to fetch" → network
 *   - any object/Error/Response carrying an HTTP status:
 *       401 / 403 / 419            → permission (auth / CSRF / session)
 *       5xx                        → server
 *       other 4xx / no signal      → unknown
 *   - a {ok:false, status?, error?} JSON payload → status-driven as above
 *
 * @param {unknown} input
 * @returns {{category:string, title:string, message:string, retryable:boolean, status:(number|null), detail:string}}
 */
export function classifyError(input) {
    let category = 'unknown';
    const status = _statusOf(input);

    const isNetwork =
        (input instanceof TypeError) ||
        (input && input.name === 'TypeError') ||
        /failed to fetch|networkerror|无法连接|连接服务器/i.test(
            String((input && input.message) || '')
        );

    if (status != null) {
        if (status === 401 || status === 403 || status === 419) category = 'permission';
        else if (status >= 500 && status <= 599) category = 'server';
        else category = 'unknown';
    } else if (isNetwork) {
        category = 'network';
    } else {
        category = 'unknown';
    }

    const tpl = TEMPLATES[category];
    // detail: prefer a payload's own error field, else the exception message.
    const rawDetail =
        (input && typeof input === 'object' && 'error' in input ? input.error : null) ||
        (input && input.message) ||
        '';
    return {
        category,
        title: tpl.title,
        message: tpl.message,
        retryable: tpl.retryable,
        status,
        detail: _detail(rawDetail),
    };
}
