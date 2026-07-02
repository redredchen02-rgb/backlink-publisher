/**
 * ui/error-capture.js — legacy-page automatic error capture (U4).
 *
 * Loaded first in base.html's script tail (before theme.js/nav.js/etc.) so it
 * can observe errors thrown by every script that loads after it. Registers a
 * capture-phase `window` 'error' listener (non-bubbling resource-load
 * failures like a broken `<img>`/`<script src>` can only be caught in the
 * capture phase) and an `unhandledrejection` listener, filters known-benign
 * noise and self-originated errors via the shared, DOM-free
 * `lib/error-capture-core.js`, and submits a sanitized report to
 * `POST /api/v1/error-reports` (Unit 3).
 *
 * Deliberately dependency-free on the notification stack: this module never
 * imports or calls into notifications.js/toast.js. It only dispatches the
 * 'app:error-captured' CustomEvent on document — the same decoupling reason
 * toast.js documents for staying independent of notifications.js, since this
 * module must be safe to load at the very front of the script tail.
 *
 * Failure handling: a submission failure (network error, non-2xx, or a CSRF
 * / session-expiry coincidence) buffers the report into localStorage (capped
 * at MAX_BUFFERED_REPORTS, mirroring notifications.js's MAX_NOTIFICATIONS
 * pattern) and retries on 'visibilitychange'/'pagehide' (not the unreliable
 * 'unload'/'beforeunload') and again the next time this module loads.
 *
 * Every entry point below is wrapped in try/catch that never re-throws to
 * the window-level listeners — a bug in this module's own capture or
 * submission logic must never itself become a new uncaught error, which
 * `isSelfOriginatedError` (core module) would otherwise catch again, forming
 * a self-reporting loop that is especially dangerous if the backend happens
 * to be down at the same time.
 */
import { readCsrf } from '../lib/api.js';
import {
    computeFingerprint,
    shouldIgnoreError,
    classifySeverity,
    DedupTracker,
} from '../lib/error-capture-core.js';

const SUBMIT_URL = '/api/v1/error-reports';
const BUFFER_KEY = 'backlink-publisher-error-report-buffer';
const MAX_BUFFERED_REPORTS = 20;
const DEDUP_WINDOW_MS = 60_000;
const SESSION_SUBMIT_CAP = 50;
const FLUSH_INTERVAL_MS = 30_000;

// app:error-captured — fired only after a report has actually been persisted
// server-side (never on a buffered-for-retry failure, and never with the
// client-minted request `reportId` — always the server's real row id). Unit
// 5/7's toast "add more detail" action reads `detail.reportId` from this.
export const ERROR_CAPTURED_EVENT = 'app:error-captured';

const tracker = new DedupTracker({ windowMs: DEDUP_WINDOW_MS, sessionCap: SESSION_SUBMIT_CAP });

// fingerprint -> last built payload for that fingerprint, used by
// flushPendingUpdates() to re-send a meaningful periodic "occurred N times"
// update. Kept here (not inside DedupTracker) so the shared tracker stays
// free of any payload-shape concept.
const lastPayloadByFingerprint = new Map();

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
        // fall through to the fallback below
    }
    return `ec-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

// ── building an errorInfo object from a raw DOM event ───────────────────────

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

// ── payload + submission ─────────────────────────────────────────────────────

function buildPayload(errorInfo, fingerprint) {
    return {
        message: errorInfo.message || '',
        stack: errorInfo.stack || null,
        url: currentUrl(),
        source: 'legacy-js',
        severity: classifySeverity(errorInfo),
        fingerprint,
        // Client-minted, throwaway TRUTHY correlation marker (see
        // webui_app/api/v1/error_reports.py module docstring) — tells the
        // server "apply fingerprint dedup", it is NOT the row id. The
        // server's response `id` is the value ever attached to a CustomEvent.
        reportId: mintCorrelationId(),
    };
}

async function submitReport(payload) {
    try {
        const resp = await fetch(SUBMIT_URL, {
            method: 'POST',
            keepalive: true,
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
            body: JSON.stringify(payload),
        });
        if (!resp.ok) return null;
        const data = await resp.json().catch(() => null);
        if (!data || !data.id) return null;
        return data;
    } catch {
        return null; // network error, CSRF/session hiccup, etc. — caller buffers
    }
}

function dispatchCaptured(reportId, message, category) {
    try {
        document.dispatchEvent(
            new CustomEvent(ERROR_CAPTURED_EVENT, { detail: { reportId, message, category } })
        );
    } catch {
        // document/CustomEvent unavailable (non-DOM context)
    }
}

async function submitOrBuffer(payload) {
    const result = await submitReport(payload);
    if (result && result.id) {
        dispatchCaptured(result.id, payload.message, payload.severity);
    } else {
        bufferReport(payload);
    }
}

// ── localStorage buffer (submission-failure fallback) ───────────────────────

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
        // storage full/unavailable — best effort only, never throw
    }
}

function bufferReport(payload) {
    const buf = readBuffer();
    buf.push(payload);
    while (buf.length > MAX_BUFFERED_REPORTS) buf.shift();
    writeBuffer(buf);
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

// ── periodic "occurred N times" flush ────────────────────────────────────────

function flushPendingUpdates() {
    const updates = tracker.collectPendingUpdates();
    for (const { fingerprint } of updates) {
        const payload = lastPayloadByFingerprint.get(fingerprint);
        if (payload) submitOrBuffer(payload);
    }
}

// ── orchestration ─────────────────────────────────────────────────────────────

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
        // Never let an internal capture/submission bug reach the window
        // listener — that would risk a self-reporting loop.
    }
}

function onErrorEvent(event) {
    try {
        handleErrorInfo(buildErrorInfoFromErrorEvent(event));
    } catch {
        // swallow — see handleErrorInfo's own try/catch rationale above
    }
}

function onRejectionEvent(event) {
    try {
        handleErrorInfo(buildErrorInfoFromRejectionEvent(event));
    } catch {
        // swallow
    }
}

function onFlushTrigger() {
    try {
        retryBufferedReports();
    } catch {
        // swallow
    }
}

function initErrorCapture() {
    window.addEventListener('error', onErrorEvent, true);
    window.addEventListener('unhandledrejection', onRejectionEvent);
    document.addEventListener('visibilitychange', onFlushTrigger);
    window.addEventListener('pagehide', onFlushTrigger);
    setInterval(() => {
        try {
            flushPendingUpdates();
        } catch {
            // swallow
        }
    }, FLUSH_INTERVAL_MS);
    // Retry anything buffered from a previous page load.
    onFlushTrigger();
}

initErrorCapture();
