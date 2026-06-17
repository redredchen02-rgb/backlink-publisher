/**
 * Unit tests for webui_app/static/js/ui/states.js (+ the toast type-fallback).
 *
 * Run with: node --test tests/js/test_ui_states.mjs
 *
 * node:test + node:assert, minimal DOM stub. Inlines el()/renderEmpty/
 * renderError/renderSkeleton — MUST stay in sync with ui/states.js — and the
 * toast type-resolution from ui/toast.js. Verifies: createElement-only building
 * (no innerHTML), callback wiring (onAction/onRetry), skeleton row count, and
 * unknown toast types falling back to 'info'.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

// ── Minimal DOM stub ──────────────────────────────────────────────────────

class FakeElement {
    constructor(tag) {
        this.tagName = tag;
        this.className = '';
        this.textContent = '';
        this.children = [];
        this._attrs = {};
        this._listeners = {};
    }
    setAttribute(k, v) { this._attrs[k] = String(v); }
    getAttribute(k) { return this._attrs[k] ?? null; }
    addEventListener(type, handler) {
        (this._listeners[type] ??= []).push(handler);
    }
    click() { (this._listeners.click || []).forEach(h => h()); }
    appendChild(child) { this.children.push(child); return child; }
    replaceChildren() { this.children = []; }
    // test helper: depth-first find by class substring
    find(cls) {
        for (const c of this.children) {
            if (typeof c === 'object' && (c.className || '').includes(cls)) return c;
            const deep = typeof c === 'object' && c.find ? c.find(cls) : null;
            if (deep) return deep;
        }
        return null;
    }
}

globalThis.document = {
    createElement: (tag) => new FakeElement(tag),
    createTextNode: (t) => ({ nodeText: t }),
};

// ── Inlined from ui/states.js (keep in sync) ──────────────────────────────

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

function renderSkeleton(container, opts = {}) {
    if (!container) return;
    const { rows = 3 } = opts;
    container.replaceChildren();
    const wrap = el('div', { class: 'ui-skeleton', role: 'status', 'aria-busy': 'true' });
    for (let i = 0; i < Math.max(1, rows); i++) wrap.appendChild(el('div', { class: 'ui-skeleton__bar' }));
    container.appendChild(wrap);
}

function renderEmpty(container, opts = {}) {
    if (!container) return;
    const { icon = 'bi-inbox', title = '暂无数据', message = '', actionLabel = '', onAction = null } = opts;
    container.replaceChildren();
    const children = [
        el('i', { class: `bi ${icon} ui-empty__icon` }),
        el('div', { class: 'ui-empty__title', text: title }),
    ];
    if (message) children.push(el('div', { class: 'ui-empty__message', text: message }));
    if (actionLabel && typeof onAction === 'function') {
        const btn = el('button', { type: 'button', class: 'ui-empty__action', text: actionLabel });
        btn.addEventListener('click', onAction);
        children.push(btn);
    }
    container.appendChild(el('div', { class: 'ui-empty', role: 'status' }, children));
}

function renderError(container, opts = {}) {
    if (!container) return;
    const { title = '出错了', message = '', retryLabel = '重试', onRetry = null } = opts;
    container.replaceChildren();
    const children = [
        el('i', { class: 'bi bi-exclamation-octagon ui-error__icon' }),
        el('div', { class: 'ui-error__title', text: title }),
    ];
    if (message) children.push(el('div', { class: 'ui-error__message', text: message }));
    if (typeof onRetry === 'function') {
        const btn = el('button', { type: 'button', class: 'ui-error__retry', text: retryLabel });
        btn.addEventListener('click', onRetry);
        children.push(btn);
    }
    container.appendChild(el('div', { class: 'ui-error', role: 'alert' }, children));
}

// toast type resolution (from ui/toast.js)
const ICONS = { success: 1, error: 1, warning: 1, info: 1 };
const resolveType = (t) => (ICONS[t] ? t : 'info');

// ── Tests ─────────────────────────────────────────────────────────────────

describe('renderEmpty', () => {
    test('happy path: renders title + message, no action when callback absent', () => {
        const c = new FakeElement('div');
        renderEmpty(c, { title: 'T', message: 'M' });
        const root = c.children[0];
        assert.equal(root.className, 'ui-empty');
        assert.ok(root.find('ui-empty__title'));
        assert.ok(root.find('ui-empty__message'));
        assert.equal(root.find('ui-empty__action'), null);
    });

    test('CTA: actionLabel + onAction wires a click that fires the callback', () => {
        const c = new FakeElement('div');
        let fired = 0;
        renderEmpty(c, { title: 'T', actionLabel: '去配置', onAction: () => { fired++; } });
        const btn = c.children[0].find('ui-empty__action');
        assert.ok(btn);
        btn.click();
        assert.equal(fired, 1);
    });

    test('edge: re-render clears prior content (no residual nodes)', () => {
        const c = new FakeElement('div');
        renderEmpty(c, { title: 'first' });
        renderEmpty(c, { title: 'second' });
        assert.equal(c.children.length, 1);
        assert.equal(c.children[0].find('ui-empty__title').textContent, 'second');
    });

    test('text goes through textContent, never innerHTML', () => {
        const c = new FakeElement('div');
        renderEmpty(c, { title: '<script>x</script>' });
        const title = c.children[0].find('ui-empty__title');
        assert.equal(title.textContent, '<script>x</script>'); // stored as text, not parsed
    });
});

describe('renderError', () => {
    test('error path: retry button fires onRetry', () => {
        const c = new FakeElement('div');
        let retried = 0;
        renderError(c, { message: 'boom', onRetry: () => { retried++; } });
        const btn = c.children[0].find('ui-error__retry');
        assert.ok(btn);
        btn.click();
        assert.equal(retried, 1);
    });

    test('no retry button when onRetry omitted', () => {
        const c = new FakeElement('div');
        renderError(c, { message: 'boom' });
        assert.equal(c.children[0].find('ui-error__retry'), null);
    });
});

describe('renderSkeleton', () => {
    test('renders requested row count, min 1', () => {
        const c = new FakeElement('div');
        renderSkeleton(c, { rows: 4 });
        assert.equal(c.children[0].children.length, 4);
        renderSkeleton(c, { rows: 0 });
        assert.equal(c.children[0].children.length, 1);
    });
});

describe('toast type fallback', () => {
    test('known types pass through, unknown -> info', () => {
        assert.equal(resolveType('success'), 'success');
        assert.equal(resolveType('error'), 'error');
        assert.equal(resolveType('nope'), 'info');
        assert.equal(resolveType(undefined), 'info');
    });
});
