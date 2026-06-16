/**
 * Notifications module — global notification center
 * Replaces Flash messages with persistent toast notifications
 */
import { on, qs, qsa, esc } from './lib/dom.js';

const NOTIFICATION_KEY = 'backlink-publisher-notifications';
const MAX_NOTIFICATIONS = 50;

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
        
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <i class="bi ${type.icon} toast-icon" style="color: ${type.color}"></i>
            <div class="toast-content">
                ${notification.title ? `<div class="toast-title">${esc(notification.title)}</div>` : ''}
                <div class="toast-message">${esc(notification.message)}</div>
            </div>
            <button type="button" class="toast-close" aria-label="关闭通知">
                <i class="bi bi-x"></i>
            </button>
        `;
        
        // Close button
        const closeBtn = toast.querySelector('.toast-close');
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
        this.badge = document.createElement('button');
        this.badge.className = 'notification-badge';
        this.badge.setAttribute('aria-label', '通知');
        this.badge.innerHTML = `
            <i class="bi bi-bell"></i>
            <span class="notification-badge__count" aria-hidden="true">0</span>
        `;
        
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
        this.panel = document.createElement('div');
        this.panel.className = 'notification-panel';
        this.panel.setAttribute('role', 'dialog');
        this.panel.setAttribute('aria-label', '通知中心');
        this.panel.innerHTML = `
            <div class="notification-panel__header">
                <span class="notification-panel__title">通知</span>
                <div class="notification-panel__actions">
                    <button type="button" class="notification-panel__btn" data-action="mark-all-read">
                        全部已读
                    </button>
                    <button type="button" class="notification-panel__btn" data-action="clear-all">
                        清空
                    </button>
                </div>
            </div>
            <div class="notification-panel__list" id="notificationList">
                <div class="notification-panel__empty">暂无通知</div>
            </div>
        `;
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
        
        if (notifications.length === 0) {
            list.innerHTML = '<div class="notification-panel__empty">暂无通知</div>';
            return;
        }
        
        list.innerHTML = notifications.map(n => {
            const type = TYPES[n.type] || TYPES.info;
            const time = this.formatTime(n.timestamp);
            return `
                <div class="notification-item ${n.read ? '' : 'unread'}" data-id="${n.id}">
                    <div class="notification-item__icon" style="background: ${type.color}20; color: ${type.color}">
                        <i class="bi ${type.icon}"></i>
                    </div>
                    <div class="notification-item__content">
                        ${n.title ? `<div class="notification-item__title">${esc(n.title)}</div>` : ''}
                        <div class="notification-item__message">${esc(n.message)}</div>
                        <div class="notification-item__time">${time}</div>
                    </div>
                </div>
            `;
        }).join('');
        
        // Bind click handlers
        qsa('.notification-item', list).forEach(el => {
            on(el, 'click', () => {
                const id = parseFloat(el.dataset.id);
                this.store.markRead(id);
                el.classList.remove('unread');
                this.updateBadge();
            });
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
    
    // Expose globally for other modules
    window.notifications = notifications;
    
    // Convert existing Flash messages
    convertFlashMessages();
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