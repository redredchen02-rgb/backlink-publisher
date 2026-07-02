/**
 * error-capture-core.js — pure, DOM-free error-capture decision logic.
 *
 * Plan 2026-07-01-002 (Frontend Error Reporting) Unit 4/Unit 6 shared module.
 *
 * This file MUST NOT touch `window`, `document`, `localStorage`, `fetch`, or any
 * other browser/DOM global — that is what lets it load natively as a zero-build
 * `<script type="module">` on the legacy Jinja pages (consumed by
 * `webui_app/static/js/ui/error-capture.js`) AND be imported unmodified into the
 * Vue/TypeScript SPA build (Unit 6, via the `frontend/vite.config.ts` `fs.allow`
 * cross-boundary import precedent already used for `tokens.css`). Plain JS/ESM
 * syntax only — no TypeScript syntax, no JSX; this file is loaded as-is by both
 * a native browser `<script type="module">` and a Vite/TS build.
 *
 * Keeping this decision logic in exactly one place is a deliberate reaction to a
 * documented failure mode in this codebase: `webui_app/static/js/ui/errors.js`
 * and `frontend/src/lib/errors.ts` were meant to be equivalent and quietly
 * diverged with no automated comparison. Noise-filtering, self-report-loop
 * guarding, severity classification, and fingerprinting must behave IDENTICALLY
 * on both frontends, so they live here once instead of two independent copies.
 *
 * Everything a consumer needs to build an "errorInfo" object for these
 * functions:
 *   - name {string}      Error/exception name, e.g. "TypeError". Default 'Error'.
 *   - message {string}   Human-readable error message.
 *   - stack {string}     Raw stack trace text (empty string/undefined if none).
 *   - filename {string}  Origin URL of the failing script/resource, if known
 *                        (e.g. an ErrorEvent's `.filename`, or a failed
 *                        `<img>`/`<script src>` element's `.src`).
 *   - source {string}    Free-form capture-site tag, e.g. 'window-error',
 *                        'unhandled-rejection', 'resource-error'. Only
 *                        `classifySeverity` reads this field today.
 * No field is required — every function tolerates a missing/undefined
 * `errorInfo` or missing individual fields and degrades to safe defaults
 * rather than throwing, since a bug in this module must never itself become
 * an uncaught error that the capture listeners then try to report.
 */

// ── message normalization ───────────────────────────────────────────────────

const UUID_PATTERN = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
const URL_PATTERN = /\bhttps?:\/\/[^\s)'"]+/gi;
const LONG_DIGIT_PATTERN = /\b\d{3,}\b/g;

/**
 * Replace volatile, per-instance content (UUIDs, absolute URLs, and long
 * digit runs such as ids/timestamps) in an error message with stable
 * placeholders, so two occurrences of "the same" logical error that differ
 * only in e.g. a request id or a timestamp normalize to the same string
 * before fingerprinting.
 *
 * @param {string} message - Raw error message. Falsy input yields ''.
 * @returns {string} Normalized message, trimmed.
 */
export function normalizeMessage(message) {
    if (!message) return '';
    return String(message)
        .replace(UUID_PATTERN, '<uuid>')
        .replace(URL_PATTERN, '<url>')
        .replace(LONG_DIGIT_PATTERN, '<num>')
        .trim();
}

// ── fingerprinting ───────────────────────────────────────────────────────────

const STACK_FRAME_COUNT = 3;

// Recognizes typical V8 ("    at foo (file:line:col)") and
// Firefox/Safari ("foo@file:line:col") stack-frame lines.
const FRAME_LINE_PATTERN = /^(at\s|\S+@)/;

function extractStackFrames(stack, count) {
    if (!stack) return [];
    const lines = String(stack)
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean);
    const frameLines = lines.filter((line) => FRAME_LINE_PATTERN.test(line));
    // Fall back to "drop the first line" (typically the "Name: message"
    // header V8 prepends) if nothing matched a recognized frame shape.
    const source = frameLines.length > 0 ? frameLines : lines.slice(1);
    return source.slice(0, count);
}

/**
 * Compute a stable, deterministic fingerprint for an error: error name +
 * normalized message (see `normalizeMessage`) + the first few stack frames.
 * Two calls with equivalent `errorInfo` (same name, message that normalizes
 * identically, same leading stack frames) always return the same string;
 * this is a non-cryptographic hash (FNV-1a, 32-bit) chosen only for speed
 * and dependency-freedom — collision-resistance against an adversary is not
 * a goal here, this is flood-control bookkeeping, not a security boundary.
 *
 * @param {{name?: string, message?: string, stack?: string}} [errorInfo]
 * @returns {string} An 8-hex-character fingerprint, e.g. "a1b2c3d4".
 */
export function computeFingerprint(errorInfo) {
    const { name = 'Error', message = '', stack = '' } = errorInfo || {};
    const normalizedMessage = normalizeMessage(message);
    const frames = extractStackFrames(stack, STACK_FRAME_COUNT);
    const basis = `${name || 'Error'}\n${normalizedMessage}\n${frames.join('\n')}`;
    return fnv1aHash(basis);
}

function fnv1aHash(str) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < str.length; i++) {
        hash ^= str.charCodeAt(i);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

// ── noise filtering ──────────────────────────────────────────────────────────

const BENIGN_MESSAGE_SUBSTRINGS = [
    'ResizeObserver loop limit exceeded',
    'ResizeObserver loop completed with undelivered notifications',
];

const EXTENSION_ORIGIN_PATTERN = /\b(?:chrome|moz)-extension:\/\//i;

/**
 * Decide whether an error is known-benign noise that should be dropped
 * outright and never treated as a reportable event: known ResizeObserver
 * loop-limit messages, errors whose origin is a browser extension
 * (`chrome-extension://` / `moz-extension://`), and a bare, stackless
 * `"Script error."` (the opaque placeholder browsers substitute for
 * cross-origin script errors with no CORS grant — NOT a filter on every
 * error that happens to be named "Script error."; one WITH a stack is a
 * real same-origin error and is not filtered).
 *
 * This function does NOT check for self-originated (capture-module) stack
 * traces — see `isSelfOriginatedError` for that orthogonal check, or use
 * `shouldIgnoreError` to combine both.
 *
 * @param {{message?: string, filename?: string, stack?: string}} [errorInfo]
 * @returns {boolean} true if this error should be dropped as noise.
 */
export function isNoiseError(errorInfo) {
    const { message = '', filename = '', stack = '' } = errorInfo || {};
    const msg = String(message || '');
    if (BENIGN_MESSAGE_SUBSTRINGS.some((benign) => msg.includes(benign))) return true;
    if (msg.trim() === 'Script error.' && !stack) return true;
    if (EXTENSION_ORIGIN_PATTERN.test(filename || '')) return true;
    if (EXTENSION_ORIGIN_PATTERN.test(stack || '')) return true;
    return false;
}

// ── self-report-loop guard ───────────────────────────────────────────────────

// Any stack frame mentioning one of these filenames means the error
// originated in the capture pipeline itself (this module, either frontend's
// DOM-layer consumer, or its submission logic) rather than in application
// code. Kept as literal filenames (not full paths) so it matches regardless
// of how the browser reports the module's URL (dev vs. built/hashed path,
// legacy `static/js/...` vs. a future bundled asset name); update this list
// if any of these files is ever renamed.
//
// `errorCapture.ts`/`errorCapturePlugin.ts` are Unit 6's Vue-side bootstrap
// (frontend/src/lib/errorCapture.ts, frontend/src/stores/errorCapturePlugin.ts)
// — added so a bug in the Vue-side capture/submission logic is guarded
// against the same self-report loop as the legacy side, per this file's own
// `isSelfOriginatedError` doc comment. Note Vite bundles to hashed chunk
// names in production, so this filename substring match is imperfect there
// (a pre-existing, accepted limitation shared with the legacy dev-vs-built
// case above, not something Unit 6 needs to solve).
const CAPTURE_MODULE_FILENAMES = [
    'error-capture-core.js',
    'error-capture.js',
    'errorCapture.ts',
    'errorCapturePlugin.ts',
];

/**
 * Decide whether a stack trace (and/or resource filename) originates from
 * the capture module itself. This guards against a self-reporting loop: a
 * bug in the submission logic could otherwise catch itself, retry, fail
 * again, and catch itself again indefinitely — especially dangerous if the
 * backend happens to be down at the same time. Callers must not submit an
 * error for which this returns true.
 *
 * @param {{stack?: string, filename?: string}} [errorInfo]
 * @returns {boolean} true if the error's stack/filename points back at this
 *   capture pipeline's own source files.
 */
export function isSelfOriginatedError(errorInfo) {
    const { stack = '', filename = '' } = errorInfo || {};
    const haystack = `${stack || ''}\n${filename || ''}`;
    return CAPTURE_MODULE_FILENAMES.some((name) => haystack.includes(name));
}

/**
 * Convenience combinator: true if `isNoiseError` OR `isSelfOriginatedError`
 * would drop this error. Prefer this in consumers (both Unit 4's
 * `error-capture.js` and Unit 6's Vue hookup) over re-deriving the OR
 * yourselves, so the "what counts as ignorable" policy can't quietly drift
 * between the two frontends.
 *
 * @param {{message?: string, filename?: string, stack?: string}} [errorInfo]
 * @returns {boolean} true if this error must NOT be submitted.
 */
export function shouldIgnoreError(errorInfo) {
    return isNoiseError(errorInfo) || isSelfOriginatedError(errorInfo);
}

// ── severity classification ──────────────────────────────────────────────────

/**
 * Auto-derive a simple, free-form severity classification from an error's
 * capture source. Intentionally coarse (kept simple per the plan): resource
 * load failures (a broken `<img>`/`<script src>`, etc.) are classified
 * `'warning'` since the page keeps functioning in a degraded state; every
 * other capture source (uncaught JS exceptions, unhandled promise
 * rejections, Vue-side hook failures) is classified `'error'`. Both this
 * module's own `error-capture.js` consumer and Unit 6 should treat this as
 * the single source of truth for the classification string sent as the
 * request body's `severity` field.
 *
 * @param {{source?: string}} [errorInfo] - `source` is a free-form
 *   capture-site tag such as 'window-error', 'unhandled-rejection', or
 *   'resource-error' (see the module-level doc comment above).
 * @returns {string} 'warning' or 'error'.
 */
export function classifySeverity(errorInfo) {
    const { source = '' } = errorInfo || {};
    return source === 'resource-error' ? 'warning' : 'error';
}

// ── in-tab dedup / flood-control tracker ─────────────────────────────────────

/**
 * Tracks fingerprint occurrences within a page's lifetime to provide
 * short-window, single-tab flood control. This is the FIRST line of
 * defense only — the server independently merges by `fingerprint` across
 * connections/tabs (Unit 3), so this tracker does not need to be, and is
 * not, a source of truth beyond a single page/tab lifetime.
 *
 * Usage: construct one instance per page load (or per app instance on the
 * Vue side) and call `record(fingerprint)` every time a non-ignored error
 * is captured, in `computeFingerprint()` order (i.e. after
 * `shouldIgnoreError` has already filtered it out). Never construct a new
 * tracker per-error — its whole purpose is to accumulate state across
 * calls.
 */
export class DedupTracker {
    /**
     * @param {{windowMs?: number, sessionCap?: number}} [options]
     * @param {number} [options.windowMs=60000] - Dedup window length, in
     *   milliseconds. The first occurrence of a fingerprint opens a window;
     *   further occurrences of the same fingerprint within the window are
     *   folded into a local count instead of resubmitting. Once the window
     *   elapses, the next occurrence of that fingerprint is treated as a
     *   new "first occurrence" and opens a fresh window.
     * @param {number} [options.sessionCap=50] - Hard ceiling on the total
     *   number of *immediate* submissions (`shouldSubmitNow: true` results)
     *   this tracker will approve for the tracker's whole lifetime — a
     *   last-resort circuit breaker independent of per-fingerprint
     *   deduping. Once reached, `record()` keeps working (never throws),
     *   it just always reports `shouldSubmitNow: false`.
     */
    constructor({ windowMs = 60_000, sessionCap = 50 } = {}) {
        this.windowMs = windowMs;
        this.sessionCap = sessionCap;
        /** @type {Map<string, {windowStart: number, count: number, lastReportedCount: number}>} */
        this._entries = new Map();
        this._submittedCount = 0;
    }

    /**
     * Record one occurrence of `fingerprint` at time `now`.
     *
     * @param {string} fingerprint - Value from `computeFingerprint()`.
     * @param {number} [now] - Epoch ms; defaults to `Date.now()`. Callers
     *   (and tests) may pass an explicit value for deterministic timing.
     * @returns {{isFirstOccurrence: boolean, occurrenceCount: number,
     *   shouldSubmitNow: boolean, capExceeded: boolean}}
     *   - `isFirstOccurrence`: true if this call opened a new window for
     *     this fingerprint (either never seen before, or its previous
     *     window had already elapsed).
     *   - `occurrenceCount`: cumulative count of this fingerprint within
     *     its current (possibly just-opened) window.
     *   - `shouldSubmitNow`: true only when this is a first occurrence AND
     *     the session cap has not been exceeded. This is the single signal
     *     callers should act on to decide "submit immediately vs. don't".
     *   - `capExceeded`: true once the session submission cap has been
     *     reached (informational — `shouldSubmitNow` already accounts for
     *     it, callers don't need to check this separately to decide
     *     whether to submit).
     */
    record(fingerprint, now = Date.now()) {
        const capExceeded = this._submittedCount >= this.sessionCap;
        const existing = this._entries.get(fingerprint);
        const windowExpired = !existing || now - existing.windowStart >= this.windowMs;

        if (windowExpired) {
            const shouldSubmitNow = !capExceeded;
            this._entries.set(fingerprint, {
                windowStart: now,
                count: 1,
                lastReportedCount: shouldSubmitNow ? 1 : 0,
            });
            if (shouldSubmitNow) this._submittedCount += 1;
            return { isFirstOccurrence: true, occurrenceCount: 1, shouldSubmitNow, capExceeded };
        }

        existing.count += 1;
        return {
            isFirstOccurrence: false,
            occurrenceCount: existing.count,
            shouldSubmitNow: false,
            capExceeded,
        };
    }

    /**
     * Collect fingerprints whose in-window count has grown since the last
     * time this method reported them, intended for a periodic ("occurred N
     * times") flush timer rather than a network call on every single
     * duplicate. Calling this repeatedly with no new occurrences in
     * between returns an empty array — each fingerprint's delta is
     * reported at most once per accumulation.
     *
     * @param {number} [now] - Unused by the current implementation; accepted
     *   for symmetry with `record()` and future window-aware filtering.
     * @returns {Array<{fingerprint: string, occurrenceCount: number}>}
     */
    collectPendingUpdates(now = Date.now()) {
        void now;
        const updates = [];
        for (const [fingerprint, entry] of this._entries.entries()) {
            if (entry.count > entry.lastReportedCount) {
                updates.push({ fingerprint, occurrenceCount: entry.count });
                entry.lastReportedCount = entry.count;
            }
        }
        return updates;
    }
}
