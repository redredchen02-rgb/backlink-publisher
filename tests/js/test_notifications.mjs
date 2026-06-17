/**
 * Unit tests for NotificationStore in webui_app/static/js/notifications.js
 *
 * Run with: node --test tests/js/test_notifications.mjs
 *
 * Uses Node.js built-in node:test + node:assert (no external deps).
 * Inlines NotificationStore + the app:notify dispatch — any divergence from
 * notifications.js is a bug. Mirrors the U3a contract: add() persists, trims to
 * MAX_NOTIFICATIONS, and dispatches an 'app:notify' CustomEvent on document.
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';

const NOTIFICATION_KEY = 'backlink-publisher-notifications';
const MAX_NOTIFICATIONS = 50;
const NOTIFY_EVENT = 'app:notify';

// ── Inline NotificationStore (MUST stay in sync with notifications.js) ──────

class NotificationStore {
    constructor() {
        this.notifications = this.load();
    }
    load() {
        try {
            const stored = localStorage.getItem(NOTIFICATION_KEY);
            return stored ? JSON.parse(stored) : [];
        } catch {
            return [];
        }
    }
    save() {
        try {
            localStorage.setItem(NOTIFICATION_KEY, JSON.stringify(this.notifications));
        } catch {
            // Storage full or unavailable
        }
    }
    add(notification) {
        const item = {
            id: Date.now() + Math.random(),
            ...notification,
            timestamp: new Date().toISOString(),
            read: false,
        };
        this.notifications.unshift(item);
        if (this.notifications.length > MAX_NOTIFICATIONS) {
            this.notifications = this.notifications.slice(0, MAX_NOTIFICATIONS);
        }
        this.save();
        try {
            document.dispatchEvent(new CustomEvent(NOTIFY_EVENT, { detail: item }));
        } catch {
            // document/CustomEvent unavailable (non-DOM context)
        }
        return item;
    }
    getUnreadCount() {
        return this.notifications.filter(n => !n.read).length;
    }
}

// ── Minimal DOM/localStorage fakes (node:test has no window/document) ───────

let _store;
let _events;

function installFakes() {
    _store = new Map();
    _events = [];
    globalThis.localStorage = {
        getItem: (k) => (_store.has(k) ? _store.get(k) : null),
        setItem: (k, v) => _store.set(k, String(v)),
        removeItem: (k) => _store.delete(k),
    };
    globalThis.CustomEvent = class CustomEvent {
        constructor(type, opts = {}) {
            this.type = type;
            this.detail = opts.detail;
        }
    };
    globalThis.document = {
        dispatchEvent: (evt) => { _events.push(evt); return true; },
    };
}

function teardownFakes() {
    delete globalThis.localStorage;
    delete globalThis.CustomEvent;
    delete globalThis.document;
}

describe('NotificationStore.add', () => {
    beforeEach(installFakes);
    afterEach(teardownFakes);

    test('happy path: dispatches app:notify with the stored item as detail', () => {
        const s = new NotificationStore();
        const item = s.add({ type: 'success', title: 'T', message: 'M' });

        assert.equal(_events.length, 1);
        assert.equal(_events[0].type, NOTIFY_EVENT);
        assert.equal(_events[0].detail, item);
        assert.equal(_events[0].detail.type, 'success');
        assert.equal(_events[0].detail.message, 'M');
        assert.equal(_events[0].detail.read, false);
    });

    test('persists to localStorage under the stable key', () => {
        const s = new NotificationStore();
        s.add({ type: 'info', message: 'hi' });
        const raw = JSON.parse(localStorage.getItem(NOTIFICATION_KEY));
        assert.equal(raw.length, 1);
        assert.equal(raw[0].message, 'hi');
    });

    test('edge: trims to MAX_NOTIFICATIONS, newest kept first', () => {
        const s = new NotificationStore();
        for (let i = 0; i < MAX_NOTIFICATIONS + 10; i++) {
            s.add({ type: 'info', message: `n${i}` });
        }
        assert.equal(s.notifications.length, MAX_NOTIFICATIONS);
        // unshift => newest first; last added survives, oldest dropped
        assert.equal(s.notifications[0].message, `n${MAX_NOTIFICATIONS + 9}`);
        assert.ok(!s.notifications.some(n => n.message === 'n0'));
        // dispatched once per add regardless of trimming
        assert.equal(_events.length, MAX_NOTIFICATIONS + 10);
    });

    test('non-DOM context: storage still succeeds when document is absent', () => {
        delete globalThis.document;
        const s = new NotificationStore();
        const item = s.add({ type: 'warning', message: 'no dom' });
        assert.equal(item.message, 'no dom');
        assert.equal(s.notifications.length, 1);
    });
});
