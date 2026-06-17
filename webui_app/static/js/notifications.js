/**
 * Notifications module — global notification center
 * Replaces Flash messages with persistent toast notifications
 */
import { on, qs, qsa } from './lib/dom.js';

const NOTIFICATION_KEY = 'backlink-publisher-notifications';
const MAX_NOTIFICATIONS = 50;

// app:notify — the cross-component notification event bus. NotificationStore.add()
// dispatches it on document; toast/badge renderers and any page module subscribe via
// document.addEventListener('app:notify', ...). Keeps cross-component signalling on
// CustomEvent (no window.* global API), per the frontend anti-rot rules.
export const NOTIFY_EVENT = 'app:notify';

// el() — tiny createElement builder so we never route untrusted text through innerHTML.
// props.text sets textContent (escaped by the DOM); props.* set attributes; children append.
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
 * Toast notification display
 */
class ToastManager {
    constructor() {
        this.container = null;
        this.init();
    }
    
    init() {
        // Create container
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        this.container.setAttribute('aria-live', 'polite');
        this.container.setAttribute('aria-atomic', 'false');
        document.body.appendChild(this.container);
        
        // Add styles
        this.addStyles();
    }
    
    addStyles() {
        if (qs('#toast-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'toast-styles';
        style.textContent = `
            .toast-container {
                position: fixed;
                top: 60px;
                right: 16px;
                z-index: 1200;
                display: flex;
                flex-direction: column;
                gap: 8px;
                max-width: 380px;
                pointer-events: none;
            }
            
            .toast {
                display: flex;
                align-items: flex-start;
                gap: 12px;
                padding: 12px 16px;
                background: var(--light);
                border: 1px solid var(--border);
                border-radius: 12px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                pointer-events: auto;
                transform: translateX(120%);
                opacity: 0;
                transition: transform 0.3s ease, opacity 0.3s ease;
            }
            
            .toast.show {
                transform: translateX(0);
                opacity: 1;
            }
            
            .toast.hiding {
                transform: translateX(120%);
                opacity: 0;
            }
            
            .toast-icon {
                font-size: 1.25rem;
                flex-shrink: 0;
                margin-top: 2px;
            }
            
            .toast-content {
                flex: 1;
                min-width: 0;
            }
            
            .toast-title {
                font-weight: 600;
                font-size: 0.9rem;
                margin-bottom: 2px;
            }
            
            .toast-message {
                font-size: 0.85rem;
                color: #6b7280;
                line-height: 1.4;
            }
            
            .toast-close {
                display: flex;
                align-items: center;
                justify-content: center;
                width: 24px;
                height: 24px;
                padding: 0;
                background: none;
                border: none;
                border-radius: 6px;
                color: #9ca3af;
                cursor: pointer;
                transition: background 0.15s ease, color 0.15s ease;
            }
            
            .toast-close:hover {
                background: rgba(0, 0, 0, 0.05);
                color: #374151;
            }
            
            .toast-progress {
                position: absolute;
                bottom: 0;
                left: 0;
                height: 3px;
                background: currentColor;
                border-radius: 0 0 12px 12px;
                opacity: 0.3;
                transition: width linear;
            }
            
            @media (max-width: 480px) {
                .toast-container {
                    left: 16px;
                    right: 16px;
                    max-width: none;
                }
            }
        `;
        document.head.appendChild(style);
    }
    
    show(notification, duration = 5000) {
        const type = TYPES[notification.type] || TYPES.info;
        
        const content = el('div', { class: 'toast-content' }, [
            notification.title ? el('div', { class: 'toast-title', text: notification.title }) : null,
            el('div', { class: 'toast-message', text: notification.message }),
        ]);
        const closeBtn = el('button', { type: 'button', class: 'toast-close', 'aria-label': '关闭通知' }, [
            el('i', { class: 'bi bi-x' }),
        ]);
        const toast = el('div', { class: 'toast', role: 'alert' }, [
            el('i', { class: `bi ${type.icon} toast-icon`, style: `color: ${type.color}` }),
            content,
            closeBtn,
        ]);

        // Close button
        on(closeBtn, 'click', () => this.hide(toast));
        
        // Add to container
        this.container.appendChild(toast);
        
        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('show');
        });
        
        // Auto-hide
        if (duration > 0) {
            setTimeout(() => this.hide(toast), duration);
        }
        
        return toast;
    }
    
    hide(toast) {
        toast.classList.remove('show');
        toast.classList.add('hiding');
        
        setTimeout(() => {
            toast.remove();
        }, 300);
    }
}

/**
 * Notification center UI
 */
class NotificationCenter {
    constructor(store) {
        this.store = store;
        this.toastManager = new ToastManager();
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
        
        // Add styles
        this.addBadgeStyles();
    }
    
    addBadgeStyles() {
        if (qs('#notification-badge-styles')) return;
        
        const style = document.createElement('style');
        style.id = 'notification-badge-styles';
        style.textContent = `
            .notification-badge {
                position: relative;
                display: flex;
                align-items: center;
                justify-content: center;
                width: 36px;
                height: 36px;
                padding: 0;
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 8px;
                color: rgba(255, 255, 255, 0.8);
                font-size: 1rem;
                cursor: pointer;
                transition: background 0.15s ease;
            }
            
            .notification-badge:hover {
                background: rgba(255, 255, 255, 0.2);
                color: #fff;
            }
            
            .notification-badge__count {
                position: absolute;
                top: -4px;
                right: -4px;
                min-width: 18px;
                height: 18px;
                padding: 0 5px;
                background: var(--danger);
                color: white;
                font-size: 0.7rem;
                font-weight: 600;
                line-height: 18px;
                text-align: center;
                border-radius: 9px;
                display: none;
            }
            
            .notification-badge__count.visible {
                display: block;
            }
            
            .notification-panel {
                position: fixed;
                top: 56px;
                right: 16px;
                width: 360px;
                max-width: calc(100vw - 32px);
                max-height: calc(100vh - 80px);
                background: var(--light);
                border: 1px solid var(--border);
                border-radius: 16px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
                z-index: 1150;
                display: none;
                flex-direction: column;
                overflow: hidden;
            }
            
            .notification-panel.open {
                display: flex;
            }
            
            .notification-panel__header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 16px;
                border-bottom: 1px solid var(--border);
            }
            
            .notification-panel__title {
                font-weight: 600;
                font-size: 1rem;
            }
            
            .notification-panel__actions {
                display: flex;
                gap: 8px;
            }
            
            .notification-panel__btn {
                padding: 4px 8px;
                background: none;
                border: none;
                border-radius: 6px;
                font-size: 0.8rem;
                color: var(--primary);
                cursor: pointer;
            }
            
            .notification-panel__btn:hover {
                background: rgba(79, 70, 229, 0.1);
            }
            
            .notification-panel__list {
                flex: 1;
                overflow-y: auto;
                padding: 8px;
            }
            
            .notification-panel__empty {
                padding: 32px 16px;
                text-align: center;
                color: #9ca3af;
            }
            
            .notification-item {
                display: flex;
                gap: 12px;
                padding: 12px;
                border-radius: 10px;
                cursor: pointer;
                transition: background 0.15s ease;
            }
            
            .notification-item:hover {
                background: rgba(79, 70, 229, 0.05);
            }
            
            .notification-item.unread {
                background: rgba(79, 70, 229, 0.08);
            }
            
            .notification-item__icon {
                width: 32px;
                height: 32px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 8px;
                flex-shrink: 0;
            }
            
            .notification-item__content {
                flex: 1;
                min-width: 0;
            }
            
            .notification-item__title {
                font-weight: 500;
                font-size: 0.9rem;
                margin-bottom: 2px;
            }
            
            .notification-item__message {
                font-size: 0.8rem;
                color: #6b7280;
                line-height: 1.4;
            }
            
            .notification-item__time {
                font-size: 0.75rem;
                color: #9ca3af;
                margin-top: 4px;
            }
        `;
        document.head.appendChild(style);
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
        const item = this.store.add(notification);
        this.toastManager.show(notification);
        this.updateBadge();
        return item;
    }
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