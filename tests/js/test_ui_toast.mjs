/**
 * Unit tests for ui/toast.js — the app:notify-driven toast renderer.
 *
 * Run with: node --test tests/js/test_ui_toast.mjs
 *
 * ui/toast.js had NO test coverage before Plan 2026-07-01-002 Unit 5. This
 * file covers its pre-existing rendering behaviour AND the Unit 5 additions
 * (the "补充说明" action button + the conditional AUTO_HIDE_MS timer), since
 * both are gated on the same `detail.reportId` signal and neither had a test
 * home until now.
 *
 * The module is fully DOM-dependent (no pure/DOM-free split like
 * error-capture-core.js), so — mirroring this directory's established
 * convention (test_notifications.mjs, test_ui_error_capture.mjs Part 2) — its
 * logic is INLINED below rather than imported. Any divergence from
 * webui_app/static/js/ui/toast.js is a bug. `render()` is given a trailing
 * `return toast` here purely for test observability; the real file has no
 * callers that need a return value, so this is a non-behavioural difference.
 *
 * Every "this is/does X" assertion is paired with a "this superficially
 * similar case does NOT do X" assertion, per this project's
 * recurring-trap-eradication convention.
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

// ── Inlined from ui/toast.js (keep in sync) ─────────────────────────────────

const NOTIFY_EVENT = 'app:notify';
const REPORT_DETAIL_EVENT = 'app:report-detail-request';
const AUTO_HIDE_MS = 5000;
const ICONS = {
    success: 'bi-check-circle-fill',
    error: 'bi-x-circle-fill',
    warning: 'bi-exclamation-triangle-fill',
    info: 'bi-info-circle-fill',
};

function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value == null || value === false) continue;
        if (key === 'text') node.textContent = value;
        else if (key === 'class') node.className = value;
        else node.setAttribute(key, value);
    }
    for (const child of children) {
        if (child == null) continue;
        node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return node;
}

let container = null;

function ensureContainer() {
    if (container && document.body.contains(container)) return container;
    container = el('div', { class: 'ui-toast-container', 'aria-live': 'polite', 'aria-atomic': 'false' });
    document.body.appendChild(container);
    return container;
}

function hide(toast) {
    toast.classList.remove('show');
    toast.classList.add('hiding');
    setTimeout(() => toast.remove(), 300);
}

// NOTE: `return toast;` added for test observability only — see file header.
function render(detail) {
    if (!detail) return null;
    const type = ICONS[detail.type] ? detail.type : 'info';
    const hasReportId = !!detail.reportId;

    const closeBtn = el('button', { type: 'button', class: 'ui-toast__close', 'aria-label': '关闭通知' }, [
        el('i', { class: 'bi bi-x' }),
    ]);

    const actionEls = [];
    if (hasReportId) {
        const detailBtn = el('button', {
            type: 'button',
            class: 'ui-toast__action',
            'aria-label': '补充说明',
            text: '补充说明',
        });
        detailBtn.addEventListener('click', () => {
            try {
                document.dispatchEvent(
                    new CustomEvent(REPORT_DETAIL_EVENT, { detail: { reportId: detail.reportId } })
                );
            } catch {
                // document/CustomEvent unavailable (non-DOM context)
            }
        });
        actionEls.push(detailBtn);
    }

    const body = el('div', { class: 'ui-toast__body' }, [
        detail.title ? el('div', { class: 'ui-toast__title', text: detail.title }) : null,
        el('div', { class: 'ui-toast__message', text: detail.message || '' }),
    ]);
    const toast = el('div', { class: `ui-toast ui-toast--${type}`, role: 'alert' }, [
        el('i', { class: `bi ${ICONS[type]} ui-toast__icon`, 'aria-hidden': 'true' }),
        body,
        ...actionEls,
        closeBtn,
    ]);
    closeBtn.addEventListener('click', () => hide(toast));
    ensureContainer().appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    if (!hasReportId) {
        setTimeout(() => hide(toast), AUTO_HIDE_MS);
    }
    return toast;
}

// ── Minimal fake DOM ─────────────────────────────────────────────────────────

function makeClassList() {
    const set = new Set();
    return {
        add: (...names) => names.forEach((n) => set.add(n)),
        remove: (...names) => names.forEach((n) => set.delete(n)),
        contains: (n) => set.has(n),
    };
}

function makeElement(tag) {
    const listeners = new Map();
    const node = {
        tagName: String(tag).toUpperCase(),
        children: [],
        parentNode: null,
        _attrs: {},
        _text: '',
        get textContent() { return this._text; },
        set textContent(v) { this._text = v == null ? '' : String(v); },
        setAttribute(k, v) { this._attrs[k] = String(v); },
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; },
        removeAttribute(k) { delete this._attrs[k]; },
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
        contains(other) {
            let cur = other;
            while (cur) { if (cur === this) return true; cur = cur.parentNode; }
            return false;
        },
        remove() {
            if (this.parentNode) {
                const idx = this.parentNode.children.indexOf(this);
                if (idx >= 0) this.parentNode.children.splice(idx, 1);
                this.parentNode = null;
            }
        },
        addEventListener(type, handler) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(handler);
        },
        dispatchEvent(evt) {
            const arr = listeners.get(evt.type) || [];
            [...arr].forEach((h) => h(evt));
            return true;
        },
    };
    node.className = '';
    node.classList = makeClassList();
    return node;
}

function findByClass(root, className) {
    const stack = [...root.children];
    const out = [];
    while (stack.length) {
        const node = stack.shift();
        if (String(node.className || '').split(/\s+/).includes(className)) out.push(node);
        stack.push(...node.children);
    }
    return out;
}

let fakeBody;
let docListeners;
let timeoutCalls;
let rafCalls;

function installFakes() {
    container = null; // reset the module-level singleton between tests
    fakeBody = makeElement('body');
    docListeners = new Map();
    timeoutCalls = [];
    rafCalls = [];

    globalThis.document = {
        body: fakeBody,
        createElement: (tag) => makeElement(tag),
        createTextNode: (text) => ({ nodeType: 3, textContent: text }),
        addEventListener(type, handler) {
            if (!docListeners.has(type)) docListeners.set(type, []);
            docListeners.get(type).push(handler);
        },
        dispatchEvent(evt) {
            const arr = docListeners.get(evt.type) || [];
            [...arr].forEach((h) => h(evt));
            return true;
        },
    };
    globalThis.CustomEvent = class CustomEvent {
        constructor(type, opts = {}) {
            this.type = type;
            this.detail = opts.detail;
        }
    };
    // Recorded, not actually scheduled — these tests only assert on WHETHER
    // (and with what delay) setTimeout was invoked, never on post-delay state.
    globalThis.setTimeout = (fn, delay) => {
        timeoutCalls.push({ fn, delay });
        return timeoutCalls.length;
    };
    // Recorded but deliberately never invoked — these tests don't assert on
    // the 'show' transition class, only on structural/content differences.
    globalThis.requestAnimationFrame = (fn) => {
        rafCalls.push(fn);
        return rafCalls.length;
    };
}

function teardownFakes() {
    delete globalThis.document;
    delete globalThis.CustomEvent;
    delete globalThis.setTimeout;
    delete globalThis.requestAnimationFrame;
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('render: baseline rendering (pre-existing behaviour)', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('renders the message/type/icon and always includes a close button', () => {
        const toast = render({ type: 'success', message: 'Saved.' });
        assert.equal(toast.className, 'ui-toast ui-toast--success');
        const closeBtns = findByClass(toast, 'ui-toast__close');
        assert.equal(closeBtns.length, 1);
    });

    test('an unrecognized type falls back to "info"', () => {
        const toast = render({ type: 'bogus', message: 'x' });
        assert.equal(toast.className, 'ui-toast ui-toast--info');
    });

    test('null detail renders nothing and does not throw', () => {
        assert.doesNotThrow(() => render(null));
        assert.equal(fakeBody.children.length, 0);
    });
});

describe('render: "补充说明" action button gated on detail.reportId', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('happy path: a reportId-bearing toast renders the action button', () => {
        const toast = render({ type: 'error', message: 'Boom', reportId: 'r-1' });
        const actions = findByClass(toast, 'ui-toast__action');
        assert.equal(actions.length, 1);
        assert.equal(actions[0].textContent, '补充说明');
    });

    test('paired: a toast with no reportId never shows the action button', () => {
        const toast = render({ type: 'error', message: 'Boom' });
        assert.equal(findByClass(toast, 'ui-toast__action').length, 0);
        // the close button is still present regardless
        assert.equal(findByClass(toast, 'ui-toast__close').length, 1);
    });

    test('clicking the action button dispatches app:report-detail-request with that reportId', () => {
        const toast = render({ type: 'error', message: 'Boom', reportId: 'r-42' });
        const [actionBtn] = findByClass(toast, 'ui-toast__action');

        let captured = null;
        document.addEventListener(REPORT_DETAIL_EVENT, (e) => { captured = e; });
        actionBtn.dispatchEvent({ type: 'click' });

        assert.ok(captured, 'app:report-detail-request must have been dispatched');
        assert.equal(captured.detail.reportId, 'r-42');
    });
});

describe('render: sticky behaviour gated on detail.reportId', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('happy path: a reportId-bearing toast does NOT schedule the AUTO_HIDE_MS timer', () => {
        render({ type: 'error', message: 'Boom', reportId: 'r-1' });
        const autoHideCalls = timeoutCalls.filter((c) => c.delay === AUTO_HIDE_MS);
        assert.equal(autoHideCalls.length, 0);
    });

    test('paired: an ordinary toast with no reportId keeps the existing 5s auto-hide unchanged', () => {
        render({ type: 'success', message: 'Saved.' });
        const autoHideCalls = timeoutCalls.filter((c) => c.delay === AUTO_HIDE_MS);
        assert.equal(autoHideCalls.length, 1);
    });

    test('manual close (via the close button) still works on a sticky reportId toast', () => {
        const toast = render({ type: 'error', message: 'Boom', reportId: 'r-1' });
        const [closeBtn] = findByClass(toast, 'ui-toast__close');
        assert.doesNotThrow(() => closeBtn.dispatchEvent({ type: 'click' }));
        // hide() -> classList transitions + a (300ms) removal timer — not the
        // 5s auto-hide timer, so the auto-hide-count assertion above is
        // unaffected by this manual close.
        assert.ok(timeoutCalls.some((c) => c.delay === 300));
    });
});
