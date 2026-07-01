/**
 * Unit tests for Plan 2026-07-01-002 Unit 4 (legacy frontend error capture).
 *
 * Run with: node --test tests/js/test_ui_error_capture.mjs
 *
 * Two-part structure, matching the split between the two source files:
 *
 * 1. `error-capture-core.js` has NO DOM dependency, so it is imported for
 *    real (unlike the rest of this test directory's inline-copy convention —
 *    there is nothing to keep "in sync" here, this IS the module).
 * 2. `ui/error-capture.js` is DOM/fetch/localStorage-dependent, so its
 *    submission/buffering glue is INLINED below (mirrors the
 *    test_notifications.mjs / test_lib_api.mjs convention in this
 *    directory: any divergence from the real file is a bug). The pure
 *    decision logic it depends on (fingerprinting, noise filtering,
 *    severity, dedup) is NOT re-inlined — it is imported for real from part 1,
 *    so these tests exercise the actual shared module Unit 6 will also import.
 *
 * Every "this is filtered / ignored / capped" assertion below is paired with
 * a "this superficially similar thing is NOT filtered / ignored / capped"
 * assertion, per this project's recurring-trap-eradication convention
 * (docs/audits/2026-05-27-recurring-trap-eradication-audit.md) — a bare
 * negative assertion here would be exactly the kind of trap that audit warns
 * cannot be caught mechanically.
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

import {
    normalizeMessage,
    computeFingerprint,
    isNoiseError,
    isSelfOriginatedError,
    shouldIgnoreError,
    classifySeverity,
    DedupTracker,
} from '../../webui_app/static/js/lib/error-capture-core.js';

function tick(ms = 0) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

// ============================================================================
// Part 1 — error-capture-core.js (imported directly, no DOM dependency)
// ============================================================================

describe('normalizeMessage', () => {
    test('replaces a UUID with a placeholder', () => {
        const msg = 'Failed to load user 4f8b6f2e-9c3a-4b1e-8e2a-1a2b3c4d5e6f';
        assert.equal(normalizeMessage(msg), 'Failed to load user <uuid>');
    });

    test('replaces an absolute URL with a placeholder', () => {
        const msg = 'GET https://api.example.com/v1/things/42 failed';
        assert.equal(normalizeMessage(msg), 'GET <url> failed');
    });

    test('replaces a long digit run (id/timestamp) with a placeholder', () => {
        assert.equal(normalizeMessage('request 1732492800123 timed out'), 'request <num> timed out');
    });

    test('paired: ordinary short text is left completely untouched', () => {
        assert.equal(normalizeMessage('Cannot read properties of undefined'), 'Cannot read properties of undefined');
        // a 1-2 digit number is NOT treated as volatile id/timestamp noise
        assert.equal(normalizeMessage('retry attempt 3 of 5'), 'retry attempt 3 of 5');
    });

    test('falsy input yields empty string', () => {
        assert.equal(normalizeMessage(''), '');
        assert.equal(normalizeMessage(undefined), '');
        assert.equal(normalizeMessage(null), '');
    });
});

describe('computeFingerprint', () => {
    test('happy path: is deterministic for the same error twice', () => {
        const errorInfo = {
            name: 'TypeError',
            message: "Cannot read properties of undefined (reading 'foo')",
            stack: "TypeError: Cannot read properties of undefined (reading 'foo')\n    at doThing (app.js:12:5)\n    at onClick (app.js:30:3)",
        };
        assert.equal(computeFingerprint(errorInfo), computeFingerprint({ ...errorInfo }));
    });

    test('paired: a genuinely different error message produces a different fingerprint', () => {
        const a = { name: 'TypeError', message: 'Cannot read x', stack: 'TypeError: Cannot read x\n    at foo (app.js:1:1)' };
        const b = { name: 'TypeError', message: 'Network request failed', stack: 'TypeError: Network request failed\n    at bar (app.js:2:2)' };
        assert.notEqual(computeFingerprint(a), computeFingerprint(b));
    });

    test('two occurrences differing only by volatile ids normalize to the SAME fingerprint', () => {
        const a = { name: 'Error', message: 'user 11111 not found', stack: 'Error: x\n    at load (app.js:9:9)' };
        const b = { name: 'Error', message: 'user 22222 not found', stack: 'Error: x\n    at load (app.js:9:9)' };
        assert.equal(computeFingerprint(a), computeFingerprint(b));
    });

    test('returns a non-empty string even for a completely empty errorInfo', () => {
        assert.equal(typeof computeFingerprint({}), 'string');
        assert.ok(computeFingerprint({}).length > 0);
        assert.equal(typeof computeFingerprint(undefined), 'string');
    });
});

describe('isNoiseError', () => {
    test('edge case: ResizeObserver loop-limit message is filtered', () => {
        assert.equal(isNoiseError({ message: 'ResizeObserver loop limit exceeded' }), true);
    });

    test('paired: a superficially similar but genuinely different message is NOT filtered', () => {
        assert.equal(
            isNoiseError({ message: 'ResizeObserver failed to attach to element #chart' }),
            false
        );
    });

    test('a bare, stackless "Script error." is filtered (cross-origin placeholder)', () => {
        assert.equal(isNoiseError({ message: 'Script error.', stack: '' }), true);
    });

    test('paired: "Script error." WITH a real stack is NOT filtered (same-origin, not the placeholder)', () => {
        assert.equal(
            isNoiseError({ message: 'Script error.', stack: 'Error: Script error.\n    at foo (app.js:1:1)' }),
            false
        );
    });

    test('an error whose filename is a chrome-extension:// origin is filtered', () => {
        assert.equal(isNoiseError({ message: 'boom', filename: 'chrome-extension://abcdefg/inject.js' }), true);
    });

    test('paired: the same message from a normal https:// origin is NOT filtered', () => {
        assert.equal(isNoiseError({ message: 'boom', filename: 'https://example.test/app.js' }), false);
    });

    test('a moz-extension:// origin appearing in the stack is filtered', () => {
        assert.equal(
            isNoiseError({ message: 'boom', stack: 'Error: boom\n    at foo (moz-extension://xyz/inject.js:1:1)' }),
            true
        );
    });

    test('missing/empty errorInfo does not throw and is not noise', () => {
        assert.equal(isNoiseError({}), false);
        assert.equal(isNoiseError(undefined), false);
    });
});

describe('isSelfOriginatedError', () => {
    test('edge case: a stack pointing at error-capture.js is self-originated', () => {
        const stack = 'Error: submission failed\n    at submitReport (webui_app/static/js/ui/error-capture.js:120:9)';
        assert.equal(isSelfOriginatedError({ stack }), true);
    });

    test('paired: a superficially similar stack from a DIFFERENT module is NOT self-originated', () => {
        const stack = 'Error: submission failed\n    at submitReport (webui_app/static/js/ui/notifications.js:120:9)';
        assert.equal(isSelfOriginatedError({ stack }), false);
    });

    test('a stack pointing at error-capture-core.js is also self-originated', () => {
        const stack = 'Error: bad fingerprint\n    at computeFingerprint (webui_app/static/js/lib/error-capture-core.js:80:5)';
        assert.equal(isSelfOriginatedError({ stack }), true);
    });

    test('paired: a filename pointing elsewhere with no stack is NOT self-originated', () => {
        assert.equal(isSelfOriginatedError({ stack: '', filename: 'https://example.test/vendor.js' }), false);
    });

    test('missing errorInfo does not throw and is not self-originated', () => {
        assert.equal(isSelfOriginatedError({}), false);
        assert.equal(isSelfOriginatedError(undefined), false);
    });
});

describe('shouldIgnoreError', () => {
    test('true when noise-filtered', () => {
        assert.equal(shouldIgnoreError({ message: 'ResizeObserver loop limit exceeded' }), true);
    });

    test('true when self-originated', () => {
        assert.equal(
            shouldIgnoreError({ stack: 'at x (webui_app/static/js/ui/error-capture.js:1:1)' }),
            true
        );
    });

    test('paired: false for a normal, unrelated, real application error', () => {
        assert.equal(
            shouldIgnoreError({ message: 'Cannot read properties of null', stack: 'at render (app.js:1:1)' }),
            false
        );
    });
});

describe('classifySeverity', () => {
    test('resource-error source classifies as warning', () => {
        assert.equal(classifySeverity({ source: 'resource-error' }), 'warning');
    });

    test('paired: window-error and unhandled-rejection sources classify as error, not warning', () => {
        assert.equal(classifySeverity({ source: 'window-error' }), 'error');
        assert.equal(classifySeverity({ source: 'unhandled-rejection' }), 'error');
    });
});

describe('DedupTracker', () => {
    test('happy path: first occurrence should submit immediately', () => {
        const tracker = new DedupTracker();
        const result = tracker.record('fp-a', 1000);
        assert.equal(result.isFirstOccurrence, true);
        assert.equal(result.occurrenceCount, 1);
        assert.equal(result.shouldSubmitNow, true);
        assert.equal(result.capExceeded, false);
    });

    test('edge case: a repeat of the SAME fingerprint within the window does not resubmit', () => {
        const tracker = new DedupTracker({ windowMs: 60_000 });
        tracker.record('fp-a', 1000);
        const second = tracker.record('fp-a', 1500);
        assert.equal(second.isFirstOccurrence, false);
        assert.equal(second.occurrenceCount, 2);
        assert.equal(second.shouldSubmitNow, false);
    });

    test('paired: a DIFFERENT fingerprint within that same window still submits immediately', () => {
        const tracker = new DedupTracker({ windowMs: 60_000 });
        tracker.record('fp-a', 1000);
        const other = tracker.record('fp-b', 1500);
        assert.equal(other.isFirstOccurrence, true);
        assert.equal(other.shouldSubmitNow, true);
    });

    test('once the window elapses, the same fingerprint is treated as first-occurrence again', () => {
        const tracker = new DedupTracker({ windowMs: 1000 });
        tracker.record('fp-a', 1000);
        const dup = tracker.record('fp-a', 1500); // still inside window
        const afterWindow = tracker.record('fp-a', 2001); // window elapsed
        assert.equal(dup.shouldSubmitNow, false);
        assert.equal(afterWindow.isFirstOccurrence, true);
        assert.equal(afterWindow.shouldSubmitNow, true);
        assert.equal(afterWindow.occurrenceCount, 1);
    });

    test('edge case: session cap stops further submissions without throwing', () => {
        const tracker = new DedupTracker({ sessionCap: 2 });
        const first = tracker.record('fp-a', 1000);
        const second = tracker.record('fp-b', 1001);
        const third = tracker.record('fp-c', 1002); // new fingerprint, but cap already hit
        assert.equal(first.shouldSubmitNow, true);
        assert.equal(second.shouldSubmitNow, true);
        assert.equal(third.shouldSubmitNow, false);
        assert.equal(third.capExceeded, true);
        assert.equal(third.isFirstOccurrence, true); // still a "new" fingerprint, just gated by the cap
        // calling it yet again must still not throw and must still refuse
        assert.doesNotThrow(() => tracker.record('fp-d', 1003));
        assert.equal(tracker.record('fp-e', 1004).shouldSubmitNow, false);
    });

    test('collectPendingUpdates reports only the delta since the last collection', () => {
        const tracker = new DedupTracker({ windowMs: 60_000 });
        tracker.record('fp-a', 1000); // first occurrence, count=1
        tracker.record('fp-a', 1100); // dup, count=2
        tracker.record('fp-a', 1200); // dup, count=3
        const updates = tracker.collectPendingUpdates(1300);
        assert.deepEqual(updates, [{ fingerprint: 'fp-a', occurrenceCount: 3 }]);

        // paired: nothing new happened -> a second collection is empty, not a repeat
        assert.deepEqual(tracker.collectPendingUpdates(1400), []);

        tracker.record('fp-a', 1500); // one more dup, count=4
        assert.deepEqual(tracker.collectPendingUpdates(1600), [{ fingerprint: 'fp-a', occurrenceCount: 4 }]);
    });
});

// ============================================================================
// Part 2 — ui/error-capture.js DOM-dependent glue (INLINED; keep in sync with
// the real file — any divergence from webui_app/static/js/ui/error-capture.js
// is a bug). Pure decision logic (fingerprint/noise/severity/dedup) is NOT
// re-inlined here; it is imported for real from Part 1's import block above.
// ============================================================================

const SUBMIT_URL = '/api/v1/error-reports';
const BUFFER_KEY = 'backlink-publisher-error-report-buffer';
const MAX_BUFFERED_REPORTS = 20;
const DEDUP_WINDOW_MS = 60_000;
const SESSION_SUBMIT_CAP = 50;
const ERROR_CAPTURED_EVENT = 'app:error-captured';

function currentUrl() {
    try {
        return window.location.href;
    } catch {
        return '';
    }
}

function mintCorrelationId() {
    try {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID();
        }
    } catch {
        // fall through
    }
    return `ec-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isResourceErrorEvent(event) {
    const target = event && event.target;
    return !!target && target !== window && typeof target.tagName === 'string';
}

function buildErrorInfoFromErrorEvent(event) {
    if (isResourceErrorEvent(event)) {
        const target = event.target;
        const src = target.src || target.href || '';
        const tag = (target.tagName || '').toLowerCase();
        return {
            name: 'ResourceError',
            message: `Failed to load resource: <${tag}> ${src}`,
            stack: '',
            filename: src,
            source: 'resource-error',
        };
    }
    const err = event.error;
    return {
        name: (err && err.name) || 'Error',
        message: event.message || (err && err.message) || '',
        stack: (err && err.stack) || '',
        filename: event.filename || '',
        source: 'window-error',
    };
}

function safeStringify(value) {
    try {
        return typeof value === 'string' ? value : JSON.stringify(value);
    } catch {
        return String(value);
    }
}

function buildErrorInfoFromRejectionEvent(event) {
    const reason = event ? event.reason : undefined;
    if (reason && typeof reason === 'object') {
        return {
            name: reason.name || 'UnhandledRejection',
            message: reason.message || safeStringify(reason),
            stack: reason.stack || '',
            filename: '',
            source: 'unhandled-rejection',
        };
    }
    return {
        name: 'UnhandledRejection',
        message: typeof reason === 'string' ? reason : safeStringify(reason),
        stack: '',
        filename: '',
        source: 'unhandled-rejection',
    };
}

function buildPayload(errorInfo, fingerprint) {
    return {
        message: errorInfo.message || '',
        stack: errorInfo.stack || null,
        url: currentUrl(),
        source: 'legacy-js',
        severity: classifySeverity(errorInfo),
        fingerprint,
        reportId: mintCorrelationId(),
    };
}

function readCsrfStub() {
    try {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return (meta && meta.content) || '';
    } catch {
        return '';
    }
}

async function submitReport(payload) {
    try {
        const resp = await fetch(SUBMIT_URL, {
            method: 'POST',
            keepalive: true,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrfStub() },
            body: JSON.stringify(payload),
        });
        if (!resp.ok) return null;
        const data = await resp.json().catch(() => null);
        if (!data || !data.id) return null;
        return data;
    } catch {
        return null;
    }
}

function dispatchCaptured(reportId, message, category) {
    try {
        document.dispatchEvent(
            new CustomEvent(ERROR_CAPTURED_EVENT, { detail: { reportId, message, category } })
        );
    } catch {
        // non-DOM context
    }
}

function readBuffer() {
    try {
        const raw = localStorage.getItem(BUFFER_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

function writeBuffer(list) {
    try {
        localStorage.setItem(BUFFER_KEY, JSON.stringify(list));
    } catch {
        // best effort
    }
}

function bufferReport(payload) {
    const buf = readBuffer();
    buf.push(payload);
    while (buf.length > MAX_BUFFERED_REPORTS) buf.shift();
    writeBuffer(buf);
}

async function submitOrBuffer(payload) {
    const result = await submitReport(payload);
    if (result && result.id) {
        dispatchCaptured(result.id, payload.message, payload.severity);
    } else {
        bufferReport(payload);
    }
}

async function retryBufferedReports() {
    const buf = readBuffer();
    if (buf.length === 0) return;
    const remaining = [];
    for (const payload of buf) {
        const result = await submitReport(payload);
        if (result && result.id) {
            dispatchCaptured(result.id, payload.message, payload.severity);
        } else {
            remaining.push(payload);
        }
    }
    writeBuffer(remaining);
}

function makeHandler(trackerOptions = {}) {
    // Fresh tracker + payload cache per test, mirroring the per-page-load
    // module-level state the real file keeps for the life of one page.
    const tracker = new DedupTracker({ windowMs: DEDUP_WINDOW_MS, sessionCap: SESSION_SUBMIT_CAP, ...trackerOptions });
    const lastPayloadByFingerprint = new Map();

    function handleErrorInfo(errorInfo) {
        try {
            if (shouldIgnoreError(errorInfo)) return;
            const fingerprint = computeFingerprint(errorInfo);
            const decision = tracker.record(fingerprint);
            const payload = buildPayload(errorInfo, fingerprint);
            lastPayloadByFingerprint.set(fingerprint, payload);
            if (!decision.shouldSubmitNow) return;
            submitOrBuffer(payload);
        } catch {
            // never propagate — mirrors error-capture.js's own guard
        }
    }

    return { tracker, handleErrorInfo };
}

// ── DOM/localStorage/fetch fakes ─────────────────────────────────────────────

let fetchCalls;
let dispatchedEvents;
let storageMap;

function installFakes({ csrfToken = 'csrf-test-token' } = {}) {
    fetchCalls = [];
    dispatchedEvents = [];
    storageMap = new Map();

    globalThis.window = { location: { href: 'https://example.test/page' } };

    globalThis.CustomEvent = class CustomEvent {
        constructor(type, opts = {}) {
            this.type = type;
            this.detail = opts.detail;
        }
    };

    globalThis.document = {
        querySelector(sel) {
            if (sel === 'meta[name="csrf-token"]') return { content: csrfToken };
            return null;
        },
        dispatchEvent(evt) {
            dispatchedEvents.push(evt);
            return true;
        },
    };

    globalThis.localStorage = {
        getItem: (k) => (storageMap.has(k) ? storageMap.get(k) : null),
        setItem: (k, v) => storageMap.set(k, String(v)),
        removeItem: (k) => storageMap.delete(k),
    };

    // Default: succeed with a fresh server id per call. Individual tests
    // override globalThis.fetch when they need failure/specific-id behavior.
    globalThis.fetch = async (url, opts) => {
        fetchCalls.push({ url, opts });
        return {
            ok: true,
            status: 201,
            json: async () => ({ id: `server-id-${fetchCalls.length}` }),
        };
    };
}

function teardownFakes() {
    delete globalThis.window;
    delete globalThis.CustomEvent;
    delete globalThis.document;
    delete globalThis.localStorage;
    delete globalThis.fetch;
}

function lastRequestBody() {
    const call = fetchCalls[fetchCalls.length - 1];
    return JSON.parse(call.opts.body);
}

describe('buildErrorInfoFromErrorEvent / buildErrorInfoFromRejectionEvent', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('plain JS error event -> window-error source with name/message/stack', () => {
        const info = buildErrorInfoFromErrorEvent({
            message: 'Boom',
            filename: 'https://example.test/app.js',
            error: { name: 'TypeError', message: 'Boom', stack: 'TypeError: Boom\n    at foo (app.js:1:1)' },
        });
        assert.equal(info.source, 'window-error');
        assert.equal(info.name, 'TypeError');
        assert.equal(info.message, 'Boom');
        assert.ok(info.stack.includes('foo'));
    });

    test('paired: a resource load failure event (target is an element) -> resource-error source', () => {
        const info = buildErrorInfoFromErrorEvent({
            target: { tagName: 'IMG', src: 'https://example.test/broken.png' },
        });
        assert.equal(info.source, 'resource-error');
        assert.ok(info.message.includes('broken.png'));
        assert.ok(info.message.includes('img'));
    });

    test('rejection with an Error reason carries its name/message/stack', () => {
        const info = buildErrorInfoFromRejectionEvent({
            reason: Object.assign(new Error('rejected!'), { name: 'RangeError' }),
        });
        assert.equal(info.source, 'unhandled-rejection');
        assert.equal(info.name, 'RangeError');
        assert.equal(info.message, 'rejected!');
    });

    test('paired: rejection with a plain string reason still produces a usable message', () => {
        const info = buildErrorInfoFromRejectionEvent({ reason: 'just a string reason' });
        assert.equal(info.source, 'unhandled-rejection');
        assert.equal(info.message, 'just a string reason');
    });
});

describe('handleErrorInfo: happy path submission', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('a plain Error produces a fingerprint + full submission payload and dispatches app:error-captured with the SERVER id', async () => {
        const { handleErrorInfo } = makeHandler();
        const errorInfo = { name: 'TypeError', message: 'Cannot read x', stack: 'TypeError: Cannot read x\n    at foo (app.js:1:1)', source: 'window-error' };

        handleErrorInfo(errorInfo);
        await tick();

        assert.equal(fetchCalls.length, 1);
        assert.equal(fetchCalls[0].url, SUBMIT_URL);
        assert.equal(fetchCalls[0].opts.method, 'POST');
        assert.equal(fetchCalls[0].opts.keepalive, true);
        assert.equal(fetchCalls[0].opts.headers['X-CSRFToken'], 'csrf-test-token');

        const body = lastRequestBody();
        assert.equal(body.message, 'Cannot read x');
        assert.ok(body.stack.includes('foo'));
        assert.equal(body.url, 'https://example.test/page');
        assert.equal(body.source, 'legacy-js');
        assert.equal(body.severity, 'error');
        assert.equal(typeof body.fingerprint, 'string');
        assert.ok(body.reportId, 'request reportId must be a truthy client-minted marker');

        assert.equal(dispatchedEvents.length, 1);
        assert.equal(dispatchedEvents[0].type, ERROR_CAPTURED_EVENT);
        assert.equal(dispatchedEvents[0].detail.reportId, 'server-id-1');
        assert.equal(dispatchedEvents[0].detail.message, 'Cannot read x');
    });

    test('new scenario: the CustomEvent reportId is the SERVER id, distinct from the client-minted request reportId', async () => {
        globalThis.fetch = async (url, opts) => {
            fetchCalls.push({ url, opts });
            return { ok: true, status: 201, json: async () => ({ id: 'abc123' }) };
        };
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({ name: 'Error', message: 'distinct-id-check', stack: 'Error: x\n    at f (app.js:5:5)' });
        await tick();

        const sentReportId = lastRequestBody().reportId;
        const dispatchedReportId = dispatchedEvents[0].detail.reportId;

        assert.equal(dispatchedReportId, 'abc123');
        assert.ok(sentReportId, 'the client-minted correlation marker must be truthy');
        assert.notEqual(
            dispatchedReportId,
            sentReportId,
            'server-assigned id and client-minted correlation id must never be conflated'
        );
    });
});

describe('handleErrorInfo: dedup window', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('the same error occurring twice within the window submits only once', async () => {
        const { handleErrorInfo } = makeHandler();
        const errorInfo = { name: 'Error', message: 'flaky thing', stack: 'Error: flaky thing\n    at f (app.js:9:9)' };

        handleErrorInfo(errorInfo);
        handleErrorInfo({ ...errorInfo });
        await tick();

        assert.equal(fetchCalls.length, 1);
    });

    test('paired: a genuinely different error within that same window still submits immediately', async () => {
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({ name: 'Error', message: 'flaky thing', stack: 'Error: flaky thing\n    at f (app.js:9:9)' });
        handleErrorInfo({ name: 'TypeError', message: 'a totally different failure', stack: 'TypeError: y\n    at g (app.js:20:2)' });
        await tick();

        assert.equal(fetchCalls.length, 2);
    });
});

describe('handleErrorInfo: noise + self-origin filtering integration', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('edge case: ResizeObserver noise never reaches fetch', async () => {
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({ name: 'Error', message: 'ResizeObserver loop limit exceeded' });
        await tick();
        assert.equal(fetchCalls.length, 0);
    });

    test('paired: a different, real error DOES reach fetch', async () => {
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({ name: 'Error', message: 'a real bug happened', stack: 'Error: x\n    at f (app.js:1:1)' });
        await tick();
        assert.equal(fetchCalls.length, 1);
    });

    test('edge case: an error whose stack originates from the capture module itself is never submitted', async () => {
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({
            name: 'TypeError',
            message: 'submission blew up',
            stack: 'TypeError: submission blew up\n    at submitReport (webui_app/static/js/ui/error-capture.js:150:5)',
        });
        await tick();
        assert.equal(fetchCalls.length, 0);
    });

    test('paired: a superficially similar error from a DIFFERENT module IS submitted', async () => {
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({
            name: 'TypeError',
            message: 'submission blew up',
            stack: 'TypeError: submission blew up\n    at doThing (webui_app/static/js/ui/some-other-module.js:150:5)',
        });
        await tick();
        assert.equal(fetchCalls.length, 1);
    });
});

describe('handleErrorInfo: session submission cap', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('edge case: once the cap is exceeded, further submissions stop without throwing', async () => {
        const { handleErrorInfo } = makeHandler({ sessionCap: 2 });
        assert.doesNotThrow(() => {
            handleErrorInfo({ name: 'Error', message: 'err-1', stack: 'Error: e1\n    at f (app.js:1:1)' });
            handleErrorInfo({ name: 'Error', message: 'err-2', stack: 'Error: e2\n    at f (app.js:2:2)' });
            handleErrorInfo({ name: 'Error', message: 'err-3', stack: 'Error: e3\n    at f (app.js:3:3)' });
            handleErrorInfo({ name: 'Error', message: 'err-4', stack: 'Error: e4\n    at f (app.js:4:4)' });
        });
        await tick();
        assert.equal(fetchCalls.length, 2);
    });
});

describe('handleErrorInfo: submission failure buffers to localStorage', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('error path: a network failure buffers the report instead of losing it', async () => {
        globalThis.fetch = async () => {
            throw new Error('network down');
        };
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({ name: 'Error', message: 'will fail to submit', stack: 'Error: x\n    at f (app.js:1:1)' });
        await tick();

        assert.equal(dispatchedEvents.length, 0, 'no success event when submission failed');
        const buffered = readBuffer();
        assert.equal(buffered.length, 1);
        assert.equal(buffered[0].message, 'will fail to submit');
    });

    test('paired: a non-2xx response also buffers (not just thrown network errors)', async () => {
        globalThis.fetch = async () => ({ ok: false, status: 403, json: async () => ({}) });
        const { handleErrorInfo } = makeHandler();
        handleErrorInfo({ name: 'Error', message: 'csrf hiccup', stack: 'Error: x\n    at f (app.js:1:1)' });
        await tick();

        assert.equal(dispatchedEvents.length, 0);
        assert.equal(readBuffer().length, 1);
    });
});

describe('retryBufferedReports: integration across "page loads"', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('a previously-buffered report is retried, and removed from the buffer only on success (never resubmitted after)', async () => {
        writeBuffer([
            { message: 'buffered from last load', stack: '', url: 'https://example.test/page', source: 'legacy-js', severity: 'error', fingerprint: 'fp-x', reportId: 'client-marker-1' },
        ]);

        // First "load": still failing.
        globalThis.fetch = async () => {
            throw new Error('still down');
        };
        await retryBufferedReports();
        assert.equal(readBuffer().length, 1, 'stays buffered while the network is still failing');
        assert.equal(dispatchedEvents.length, 0);

        // Second "load": backend recovered.
        globalThis.fetch = async (url, opts) => {
            fetchCalls.push({ url, opts });
            return { ok: true, status: 200, json: async () => ({ id: 'recovered-id-1', occurrences: 2 }) };
        };
        await retryBufferedReports();
        assert.equal(readBuffer().length, 0, 'removed from the buffer once the retry succeeds');
        assert.equal(dispatchedEvents.length, 1);
        assert.equal(dispatchedEvents[0].detail.reportId, 'recovered-id-1');

        // Third "load": buffer is empty, must not resubmit the same report again.
        const callsBefore = fetchCalls.length;
        await retryBufferedReports();
        assert.equal(fetchCalls.length, callsBefore, 'nothing left to retry -> no additional fetch call');
        assert.equal(dispatchedEvents.length, 1, 'still exactly one success event ever — not submitted twice');
    });
});

describe('localStorage buffer cap', () => {
    beforeEach(() => installFakes());
    afterEach(teardownFakes);

    test('edge case: the buffer never grows past MAX_BUFFERED_REPORTS', () => {
        for (let i = 0; i < MAX_BUFFERED_REPORTS + 5; i++) {
            bufferReport({ message: `overflow-${i}`, stack: '', url: '', source: 'legacy-js', severity: 'error', fingerprint: `fp-${i}`, reportId: true });
        }
        const buf = readBuffer();
        assert.equal(buf.length, MAX_BUFFERED_REPORTS);
        // oldest entries are dropped, newest survive
        assert.ok(!buf.some((r) => r.message === 'overflow-0'));
        assert.ok(buf.some((r) => r.message === `overflow-${MAX_BUFFERED_REPORTS + 4}`));
    });
});
