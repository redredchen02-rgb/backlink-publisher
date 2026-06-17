/**
 * Unit tests for the sidebar anomaly badge logic in ui/nav-badge.js (U7).
 *
 * Run with: node --test tests/js/test_ui_nav_badge.mjs
 *
 * Inlines the count-resolution + badge-set logic (keep in sync with nav-badge.js):
 * hidden at zero, shown with accessible label at >0, fail-open on bad data.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

// ── Inlined from ui/nav-badge.js (keep in sync) ───────────────────────────

function resolveCount(data) {
    return (data && data.ok !== false && Number(data.anomaly_count)) || 0;
}

function applyBadge(badge, count) {
    if (count > 0) {
        badge.textContent = String(count);
        badge.setAttribute('aria-label', `监控聚合：${count} 项异常`);
        badge.hidden = false;
    } else {
        badge.textContent = '';
        badge.removeAttribute('aria-label');
        badge.hidden = true;
    }
}

// minimal badge stub
function makeBadge() {
    return {
        textContent: 'x',
        hidden: false,
        _attrs: {},
        setAttribute(k, v) { this._attrs[k] = v; },
        removeAttribute(k) { delete this._attrs[k]; },
    };
}

describe('resolveCount', () => {
    test('reads anomaly_count from a healthy payload', () => {
        assert.equal(resolveCount({ ok: true, anomaly_count: 3 }), 3);
    });
    test('ok=false -> 0 (fail-open)', () => {
        assert.equal(resolveCount({ ok: false, anomaly_count: 9 }), 0);
    });
    test('missing / malformed -> 0', () => {
        assert.equal(resolveCount(null), 0);
        assert.equal(resolveCount({}), 0);
        assert.equal(resolveCount({ ok: true, anomaly_count: 'nope' }), 0);
    });
});

describe('applyBadge', () => {
    test('count > 0 shows badge with accessible label', () => {
        const b = makeBadge();
        applyBadge(b, 2);
        assert.equal(b.hidden, false);
        assert.equal(b.textContent, '2');
        assert.equal(b._attrs['aria-label'], '监控聚合：2 项异常');
    });
    test('count 0 hides badge and drops the label (no "0" noise)', () => {
        const b = makeBadge();
        applyBadge(b, 0);
        assert.equal(b.hidden, true);
        assert.equal(b.textContent, '');
        assert.equal(b._attrs['aria-label'], undefined);
    });
});
