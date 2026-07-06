/**
 * Unit tests for ui/error-report-entry.js — the nav-bar "report a problem"
 * entry + shared panel (manual POST path, toast-triggered PATCH path).
 *
 * Run with: node --test tests/js/test_ui_error_report_entry.mjs
 *
 * Mirrors this directory's established convention (test_notifications.mjs,
 * test_ui_error_capture.mjs, test_ui_toast.mjs): the module is fully
 * DOM-dependent with load-time wiring, so its logic is INLINED below rather
 * than imported. Any divergence from webui_app/static/js/ui/error-report-entry.js
 * is a bug.
 *
 * Every "this is/does X" assertion is paired with a "this superficially
 * similar case does NOT do X" assertion, per this project's
 * recurring-trap-eradication convention.
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

// ── Inlined from ui/error-report-entry.js (keep in sync) ───────────────────

const POST_URL = '/api/v1/error-reports';
const MOUNT_SELECTOR = '.app-topbar__actions';
const BUTTON_ID = 'reportProblemBtn';
const REPORT_DETAIL_EVENT = 'app:report-detail-request';

function patchUrl(reportId) {
    return `/api/v1/error-reports/${encodeURIComponent(reportId)}`;
}

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

function isBlankInput(text) {
    return !text || !String(text).trim();
}

function buildManualReportBody(text) {
    return { message: String(text).trim(), source: 'manual', severity: 'error' };
}

function buildDescriptionBody(text) {
    return { description: String(text).trim() };
}

async function postManualReport(text) {
    const resp = await fetch(POST_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
        body: JSON.stringify(buildManualReportBody(text)),
    });
    if (!resp.ok) {
        const err = new Error(`manual report submit failed: HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return resp.json().catch(() => ({}));
}

async function patchReportDescription(reportId, text) {
    const resp = await fetch(patchUrl(reportId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
        body: JSON.stringify(buildDescriptionBody(text)),
    });
    if (!resp.ok) {
        const err = new Error(`report description update failed: HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return resp.json().catch(() => ({}));
}

function notifySuccess(message) {
    const center = getNotificationCenter();
    if (center) center.success(message);
}

class ReportPanel {
    constructor() {
        this.reportId = null;
        this.isOpen = false;
        this._triggerEl = null;
        this._build();
        this._bindGlobalEvents();
    }

    _build() {
        this.titleEl = el('span', { class: 'error-report-panel__title', text: '回报问题' });
        const closeBtn = el('button', {
            type: 'button', class: 'error-report-panel__close', 'aria-label': '关闭面板',
        }, [el('i', { class: 'bi bi-x' })]);
        closeBtn.addEventListener('click', () => this.close());
        const header = el('div', { class: 'error-report-panel__header' }, [this.titleEl, closeBtn]);

        this.textarea = el('textarea', {
            class: 'error-report-panel__input',
            rows: '4',
            placeholder: '请描述您遇到的问题…',
            'aria-label': '问题描述',
        });

        this.errorBox = el('div', { class: 'error-report-panel__error', role: 'alert' });
        this.errorBox.hidden = true;

        const dashboardLink = el('a', {
            href: '/app/error-reports',
            class: 'error-report-panel__dashboard-link',
            text: '查看完整错误报告仪表板',
        });

        const cancelBtn = el('button', {
            type: 'button', class: 'error-report-panel__cancel', text: '取消',
        });
        cancelBtn.addEventListener('click', () => this.close());

        this.submitBtn = el('button', {
            type: 'button', class: 'error-report-panel__submit', text: '提交',
        });
        this.submitBtn.addEventListener('click', () => this._submit());

        const actions = el('div', { class: 'error-report-panel__actions' }, [cancelBtn, this.submitBtn]);
        const body = el('div', { class: 'error-report-panel__body' }, [
            this.textarea, this.errorBox, dashboardLink, actions,
        ]);

        this.panel = el('div', {
            class: 'error-report-panel', role: 'dialog', 'aria-label': '回报问题',
        }, [header, body]);
        this.panel.hidden = true;

        document.body.appendChild(this.panel);
    }

    _bindGlobalEvents() {
        document.addEventListener('click', (e) => {
            if (!this.isOpen) return;
            const insidePanel = this.panel.contains(e.target);
            const onTrigger = this._triggerEl ? this._triggerEl.contains(e.target) : false;
            if (!insidePanel && !onTrigger) this.close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) this.close();
        });
    }

    open({ reportId = null, triggerEl = null } = {}) {
        this.reportId = reportId || null;
        this._triggerEl = triggerEl || null;
        this.textarea.value = '';
        this._hideError();
        this.titleEl.textContent = this.reportId ? '补充说明' : '回报问题';
        this.textarea.placeholder = this.reportId
            ? '请补充这个问题的更多细节…'
            : '请描述您遇到的问题…';
        this.panel.hidden = false;
        this.isOpen = true;
        try { this.textarea.focus(); } catch { /* focus not available everywhere */ }
    }

    close() {
        this.panel.hidden = true;
        this.isOpen = false;
    }

    _showError(message) {
        this.errorBox.textContent = message;
        this.errorBox.hidden = false;
    }

    _hideError() {
        this.errorBox.textContent = '';
        this.errorBox.hidden = true;
    }

    async _submit() {
        const text = this.textarea.value;
        if (isBlankInput(text)) {
            this._showError('请输入内容后再提交。');
            return;
        }
        this._hideError();
        try {
            if (this.reportId) {
                await patchReportDescription(this.reportId, text);
                this.close();
                notifySuccess('补充说明已提交，感谢您的反馈。');
            } else {
                await postManualReport(text);
                this.close();
                notifySuccess('问题反馈已提交，感谢您的报告。');
            }
        } catch (err) {
            this._showError(classifyError(err).message);
        }
    }
}

function initErrorReportEntry() {
    const panel = new ReportPanel();

    const container = document.querySelector(MOUNT_SELECTOR);
    const button = container && container.querySelector(`#${BUTTON_ID}`);
    if (button) {
        button.addEventListener('click', () => panel.open({ triggerEl: button }));
    }

    document.addEventListener(REPORT_DETAIL_EVENT, (e) => {
        const reportId = e && e.detail && e.detail.reportId;
        if (!reportId) return;
        panel.open({ reportId });
    });

    return panel;
}

// ── Minimal fake DOM (mirrors tests/js/test_ui_toast.mjs) ───────────────────

function makeClassList(node) {
    return {
        add: (...names) => names.forEach((n) => { node._classes.add(n); }),
        remove: (...names) => names.forEach((n) => { node._classes.delete(n); }),
        contains: (n) => node._classes.has(n),
    };
}

function matchesSelector(node, sel) {
    if (sel.startsWith('#')) return node._attrs.id === sel.slice(1);
    if (sel.startsWith('.')) return String(node.className || '').split(/\s+/).includes(sel.slice(1));
    return false;
}

function queryDescendants(root, sel) {
    const stack = [...root.children];
    while (stack.length) {
        const node = stack.shift();
        if (matchesSelector(node, sel)) return node;
        stack.push(...node.children);
    }
    return null;
}

function makeElement(tag) {
    const listeners = new Map();
    const node = {
        tagName: String(tag).toUpperCase(),
        children: [],
        parentNode: null,
        _attrs: {},
        _classes: new Set(),
        _text: '',
        hidden: false,
        value: '',
        get textContent() { return this._text; },
        set textContent(v) { this._text = v == null ? '' : String(v); },
        setAttribute(k, v) { this._attrs[k] = String(v); if (k === 'class') this.className = String(v); },
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; },
        removeAttribute(k) { delete this._attrs[k]; },
        appendChild(child) { this.children.push(child); child.parentNode = this; return child; },
        contains(other) {
            let cur = other;
            while (cur) { if (cur === this) return true; cur = cur.parentNode; }
            return false;
        },
        querySelector(sel) { return queryDescendants(this, sel); },
        addEventListener(type, handler) {
            if (!listeners.has(type)) listeners.set(type, []);
            listeners.get(type).push(handler);
        },
        dispatchEvent(evt) {
            const arr = listeners.get(evt.type) || [];
            [...arr].forEach((h) => h(evt));
            return true;
        },
        focus() {},
    };
    Object.defineProperty(node, 'className', {
        get() { return [...node._classes].join(' '); },
        set(v) { node._classes = new Set(String(v || '').split(/\s+/).filter(Boolean)); },
    });
    node.classList = makeClassList(node);
    return node;
}

let fakeBody;
let docListeners;
let fetchCalls;
let notifySuccessCalls;

function installFakes() {
    fakeBody = makeElement('body');
    docListeners = new Map();
    fetchCalls = [];
    notifySuccessCalls = [];

    globalThis.document = {
        body: fakeBody,
        createElement: (tag) => makeElement(tag),
        createTextNode: (text) => ({ nodeType: 3, textContent: text }),
        querySelector(sel) { return queryDescendants(fakeBody, sel); },
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

    globalThis.readCsrf = () => 'csrf-test-token';
    globalThis.getNotificationCenter = () => ({
        success: (message) => notifySuccessCalls.push(message),
    });
    globalThis.classifyError = (err) => ({ message: (err && err.message) || '未知错误' });

    globalThis.fetch = async (url, opts) => {
        fetchCalls.push({ url, opts });
        return { ok: true, status: 200, json: async () => ({ id: 'server-id-1' }) };
    };
}

function teardownFakes() {
    delete globalThis.document;
    delete globalThis.CustomEvent;
    delete globalThis.readCsrf;
    delete globalThis.getNotificationCenter;
    delete globalThis.classifyError;
    delete globalThis.fetch;
}

function mountTopbarButton() {
    const button = el('button', { id: BUTTON_ID, class: 'topbar-btn' });
    const container = el('div', { class: 'app-topbar__actions' }, [button]);
    fakeBody.appendChild(container);
    return { container, button };
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('ReportPanel: manual report submit path (no reportId)', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('edge case: blank input is blocked, shows inline error, does not call fetch', async () => {
        const panel = initErrorReportEntry();
        panel.open({});
        panel.textarea.value = '   ';
        await panel._submit();

        assert.equal(fetchCalls.length, 0);
        assert.equal(panel.errorBox.hidden, false);
        assert.equal(panel.isOpen, true);
    });

    test('happy path: non-blank submit POSTs {message, source, severity} with NO reportId key, then closes + notifies', async () => {
        const panel = initErrorReportEntry();
        panel.open({});
        panel.textarea.value = '按钮点击没有反应';
        await panel._submit();

        assert.equal(fetchCalls.length, 1);
        assert.equal(fetchCalls[0].url, POST_URL);
        assert.equal(fetchCalls[0].opts.method, 'POST');
        const body = JSON.parse(fetchCalls[0].opts.body);
        assert.equal(body.message, '按钮点击没有反应');
        assert.equal(body.source, 'manual');
        assert.equal(body.severity, 'error');
        assert.ok(!('reportId' in body), 'manual submit must never send a reportId key');

        assert.equal(panel.isOpen, false);
        assert.equal(notifySuccessCalls.length, 1);
    });

    test('paired: a failed manual submit shows an inline error and leaves the panel open', async () => {
        globalThis.fetch = async () => ({ ok: false, status: 502 });
        const panel = initErrorReportEntry();
        panel.open({});
        panel.textarea.value = '同样的输入';
        await panel._submit();

        assert.equal(panel.isOpen, true);
        assert.equal(panel.errorBox.hidden, false);
        assert.equal(notifySuccessCalls.length, 0);
    });
});

describe('ReportPanel: toast "补充说明" -> PATCH path (reportId present)', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('happy path: app:report-detail-request opens the panel pre-filled with reportId', () => {
        const panel = initErrorReportEntry();
        document.dispatchEvent(new CustomEvent(REPORT_DETAIL_EVENT, { detail: { reportId: 'r-99' } }));

        assert.equal(panel.isOpen, true);
        assert.equal(panel.reportId, 'r-99');
    });

    test('paired: app:report-detail-request with no reportId does not open the panel', () => {
        const panel = initErrorReportEntry();
        document.dispatchEvent(new CustomEvent(REPORT_DETAIL_EVENT, { detail: {} }));
        assert.equal(panel.isOpen, false);
    });

    test('submitting with a reportId PATCHes that id with {description}, then closes + notifies', async () => {
        const panel = initErrorReportEntry();
        document.dispatchEvent(new CustomEvent(REPORT_DETAIL_EVENT, { detail: { reportId: 'r-42' } }));
        panel.textarea.value = '补充：只有在 Safari 上会发生';
        await panel._submit();

        assert.equal(fetchCalls.length, 1);
        assert.equal(fetchCalls[0].url, patchUrl('r-42'));
        assert.equal(fetchCalls[0].opts.method, 'PATCH');
        const body = JSON.parse(fetchCalls[0].opts.body);
        assert.equal(body.description, '补充：只有在 Safari 上会发生');

        assert.equal(panel.isOpen, false);
        assert.equal(notifySuccessCalls.length, 1);
    });
});

describe('mount integration: nav-bar button', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('integration: the button is looked up scoped through .app-topbar__actions and wired to open the panel', () => {
        mountTopbarButton();
        const panel = initErrorReportEntry();

        const container = document.querySelector(MOUNT_SELECTOR);
        assert.ok(container, '.app-topbar__actions must be found');
        const button = container.querySelector(`#${BUTTON_ID}`);
        assert.ok(button, '#reportProblemBtn must be found scoped inside the container');

        assert.equal(panel.isOpen, false);
        button.dispatchEvent({ type: 'click', target: button });
        assert.equal(panel.isOpen, true);
    });

    test('paired: with no topbar button present, init does not throw and the toast-triggered path still works', () => {
        assert.doesNotThrow(() => {
            const panel = initErrorReportEntry();
            document.dispatchEvent(new CustomEvent(REPORT_DETAIL_EVENT, { detail: { reportId: 'r-1' } }));
            assert.equal(panel.isOpen, true);
        });
    });
});
