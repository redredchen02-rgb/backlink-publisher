/**
 * Notifications module — global notification center
 * Replaces Flash messages with persistent toast notifications
 */
import { on, qs, qsa, el } from './lib/dom.js';

const NOTIFICATION_KEY = 'backlink-publisher-notifications';
const MAX_NOTIFICATIONS = 50;

// app:notify — the cross-component notification event bus. NotificationStore.add()
// dispatches it on document; toast/badge renderers and any page module subscribe via
// document.addEventListener('app:notify', ...). Keeps cross-component signalling on
// CustomEvent (no window.* global API), per the frontend anti-rot rules.
export const NOTIFY_EVENT = 'app:notify';

// el() is imported from ./lib/dom.js — shared across all page modules.
}

/**
 * Notification types
 */
const TYPES = {
    success: { icon: 'bi-check-circle-fill', color: 'var(--success)' },
    error: { icon: 'bi-x-circle-fill', color: 'var(--danger)' },
    warning: { icon: 'bi-exclamation-triangle-fill', color: 'var(--warning)' },
    info: { icon: 'bi-info-circle-fill', color: 'var(--info)' },
};

/**
 * Notification store
 */
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
    
    // notification may carry an optional `reportId` passthrough field (Unit 5,
    // Plan 2026-07-01-002): when bindErrorCaptureBridge() below calls
    // notifications.add({..., reportId}), it flows unchanged through this
    // object spread into the persisted item AND the app:notify detail below —
    // no structural change to this method was needed. ui/toast.js reads
    // detail.reportId to render a "补充说明" action and to skip its auto-hide
    // timer for that toast.
    add(notification) {
        const item = {
            id: Date.now() + Math.random(),
            ...notification,
            timestamp: new Date().toISOString(),
            read: false,
        };
        
        this.notifications.unshift(item);
        
        // Trim to max
        if (this.notifications.length > MAX_NOTIFICATIONS) {
            this.notifications = this.notifications.slice(0, MAX_NOTIFICATIONS);
        }
        
        this.save();

        // Dispatch on the document so toast/badge renderers and page modules can react
        // without a window.* global. detail is the stored item (id/type/title/message/...).
        try {
            document.dispatchEvent(new CustomEvent(NOTIFY_EVENT, { detail: item }));
        } catch {
            // document/CustomEvent unavailable (non-DOM context) — storage still succeeded.
        }

        return item;
    }

    markRead(id) {
        const item = this.notifications.find(n => n.id === id);
        if (item) {
            item.read = true;
            this.save();
        }
    }
    
    markAllRead() {
        this.notifications.forEach(n => n.read = true);
        this.save();
    }
    
    clear() {
        this.notifications = [];
        this.save();
    }
    
    getUnreadCount() {
        return this.notifications.filter(n => !n.read).length;
    }
    
    getRecent(count = 10) {
        return this.notifications.slice(0, count);
    }
}

/**
 * Notification center UI
 */
class NotificationCenter {
    constructor(store) {
        this.store = store;
        // Toasts are rendered by ui/toast.js subscribing to the app:notify event
        // that store.add() dispatches — this class only owns the bell badge + panel.
        this.panel = null;
        this.badge = null;
        this.isOpen = false;
        
        this.init();
    }
    
    init() {
        this.createBadge();
        this.createPanel();
        this.bindEvents();
        this.updateBadge();
    }
    
    createBadge() {
        this.badge = el('button', { class: 'notification-badge', 'aria-label': '通知' }, [
            el('i', { class: 'bi bi-bell' }),
            el('span', { class: 'notification-badge__count', 'aria-hidden': 'true', text: '0' }),
        ]);

        // Insert before theme toggle
        const actions = qs('.global-nav__actions');
        if (actions) {
            actions.insertBefore(this.badge, actions.firstChild);
        }
        
        // Styles are in static/css/notifications.css — no inline injection.
    }
    
    createPanel() {
        const header = el('div', { class: 'notification-panel__header' }, [
            el('span', { class: 'notification-panel__title', text: '通知' }),
            el('div', { class: 'notification-panel__actions' }, [
                el('button', { type: 'button', class: 'notification-panel__btn', 'data-action': 'mark-all-read', text: '全部已读' }),
                el('button', { type: 'button', class: 'notification-panel__btn', 'data-action': 'clear-all', text: '清空' }),
            ]),
        ]);
        const list = el('div', { class: 'notification-panel__list', id: 'notificationList' }, [
            el('div', { class: 'notification-panel__empty', text: '暂无通知' }),
        ]);
        this.panel = el('div', { class: 'notification-panel', role: 'dialog', 'aria-label': '通知中心' }, [header, list]);
        document.body.appendChild(this.panel);
        
        this.renderList();
    }
    
    bindEvents() {
        // Toggle panel
        on(this.badge, 'click', () => this.toggle());
        
        // Close on outside click
        on(document, 'click', (e) => {
            if (this.isOpen && 
                !this.panel.contains(e.target) && 
                !this.badge.contains(e.target)) {
                this.close();
            }
        });
        
        // Close on escape
        on(document, 'keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) {
                this.close();
            }
        });
        
        // Panel actions
        on(this.panel, 'click', (e) => {
            const action = e.target.closest('[data-action]');
            if (action) {
                const actionType = action.dataset.action;
                if (actionType === 'mark-all-read') {
                    this.store.markAllRead();
                    this.renderList();
                    this.updateBadge();
                } else if (actionType === 'clear-all') {
                    this.store.clear();
                    this.renderList();
                    this.updateBadge();
                }
            }
        });
    }
    
    toggle() {
        this.isOpen ? this.close() : this.open();
    }
    
    open() {
        this.panel.classList.add('open');
        this.isOpen = true;
        this.renderList();
    }
    
    close() {
        this.panel.classList.remove('open');
        this.isOpen = false;
    }
    
    updateBadge() {
        const count = this.store.getUnreadCount();
        const countEl = this.badge.querySelector('.notification-badge__count');
        if (countEl) {
            countEl.textContent = count;
            countEl.classList.toggle('visible', count > 0);
        }
    }
    
    renderList() {
        const list = qs('#notificationList', this.panel);
        const notifications = this.store.getRecent(20);

        list.replaceChildren();

        if (notifications.length === 0) {
            list.appendChild(el('div', { class: 'notification-panel__empty', text: '暂无通知' }));
            return;
        }

        notifications.forEach(n => {
            const type = TYPES[n.type] || TYPES.info;
            const content = el('div', { class: 'notification-item__content' }, [
                n.title ? el('div', { class: 'notification-item__title', text: n.title }) : null,
                el('div', { class: 'notification-item__message', text: n.message }),
                el('div', { class: 'notification-item__time', text: this.formatTime(n.timestamp) }),
            ]);
            const item = el('div', {
                class: `notification-item ${n.read ? '' : 'unread'}`.trim(),
                'data-id': n.id,
            }, [
                el('div', { class: 'notification-item__icon', style: `background: ${type.color}20; color: ${type.color}` }, [
                    el('i', { class: `bi ${type.icon}` }),
                ]),
                content,
            ]);
            on(item, 'click', () => {
                this.store.markRead(parseFloat(item.dataset.id));
                item.classList.remove('unread');
                this.updateBadge();
            });
            list.appendChild(item);
        });
    }
    
    formatTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) return '刚刚';
        if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
        return `${Math.floor(diff / 86400000)} 天前`;
    }
    
    // Public API
    success(message, title = '') {
        return this.add({ type: 'success', title, message });
    }
    
    error(message, title = '') {
        return this.add({ type: 'error', title, message });
    }
    
    warning(message, title = '') {
        return this.add({ type: 'warning', title, message });
    }
    
    info(message, title = '') {
        return this.add({ type: 'info', title, message });
    }
    
    add(notification) {
        // store.add() persists AND dispatches app:notify (ui/toast.js renders the
        // toast). We only refresh the unread badge here.
        const item = this.store.add(notification);
        this.updateBadge();
        return item;
    }
}

// app:error-captured — dispatched by ui/error-capture.js (Unit 4) on `document`
// ONLY after a report has been persisted server-side; detail.reportId is the
// server's real row id (safe to PATCH against immediately), detail.message is
// the error message, and detail.category is classifySeverity()'s output
// ('warning'|'error') despite the parameter's name there — treated here as
// the toast's severity/type. Kept as a literal (not imported from
// ui/error-capture.js) for the same decoupling reason NOTIFY_EVENT is kept as
// a literal in ui/toast.js: importing would tie this module's execution
// order to error-capture.js's, and this module must stay safe to init
// regardless of that script's tag position. Keep this string in sync with
// ui/error-capture.js's ERROR_CAPTURED_EVENT export.
//
// Before this bridge existed, NOTHING consumed this event — Unit 4's
// auto-captured errors were persisted server-side but never became a visible
// toast. This listener is that missing link into the existing app:notify /
// ui/toast.js pipeline.
const ERROR_CAPTURED_EVENT = 'app:error-captured';

// classifySeverity() (lib/error-capture-core.js) only ever returns 'warning'
// or 'error'; this defensively maps anything else to 'error' too, since
// every event on this bus is by definition an error report.
function mapErrorCaptureCategoryToType(category) {
    return category === 'warning' ? 'warning' : 'error';
}

function bindErrorCaptureBridge() {
    document.addEventListener(ERROR_CAPTURED_EVENT, (e) => {
        const detail = (e && e.detail) || {};
        notifications.add({
            type: mapErrorCaptureCategoryToType(detail.category),
            message: detail.message,
            reportId: detail.reportId,
        });
    });
}

// Global instance
let notifications = null;

/**
 * Initialize notifications
 */
function initNotifications() {
    const store = new NotificationStore();
    notifications = new NotificationCenter(store);

    // Other modules subscribe via document.addEventListener('app:notify', ...) — no window.* global.
    // Convert existing Flash messages
    convertFlashMessages();
    bindErrorCaptureBridge();
}

// Module export for consumers that need the live center (e.g. to call .success()/.error()).
// Cross-component signalling otherwise goes through the app:notify event, not this binding.
export function getNotificationCenter() {
    return notifications;
}

/**
 * Convert existing Flash messages to notifications
 */
function convertFlashMessages() {
    const flashEls = qsa('.alert-dismissible');
    flashEls.forEach(el => {
        const type = el.classList.contains('alert-success') ? 'success' :
                    el.classList.contains('alert-danger') ? 'error' :
                    el.classList.contains('alert-warning') ? 'warning' : 'info';
        const message = el.textContent.trim();
        
        if (message) {
            notifications.add({ type, message });
            el.remove();
        }
    });
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNotifications);
} else {
    initNotifications();
}