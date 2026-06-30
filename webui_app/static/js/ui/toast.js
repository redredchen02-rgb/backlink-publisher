/**
 * ui/toast.js — console-style toast renderer driven by the app:notify event bus.
 *
 * NotificationStore.add() (notifications.js) dispatches CustomEvent('app:notify',
 * {detail}) on document. This module is the single toast renderer: it subscribes
 * once and builds each toast with createElement (no innerHTML). Type colour/icon
 * come from CSS classes (toast--<type>) in components.css, not inline JS styles —
 * so there is no JS↔token colour coupling and no inline style injection.
 *
 * The container offset is driven by the --toast-top CSS variable (components.css),
 * not a hardcoded topbar height, so it survives the shell rework.
 *
 * The event name is intentionally a literal (NOT imported from notifications.js):
 * importing would execute notifications.js's module body — which dispatches flash
 * events on init — BEFORE this listener attaches, dropping the first toasts. By
 * staying decoupled and loading this script tag first, the listener is always
 * ready before notifications.js inits. Keep in sync with NOTIFY_EVENT there.
 */
const NOTIFY_EVENT = 'app:notify';

const AUTO_HIDE_MS = 5000;
const ICONS = {
    success: 'bi-check-circle-fill',
    error: 'bi-x-circle-fill',
    warning: 'bi-exclamation-triangle-fill',
    info: 'bi-info-circle-fill',
};

import { el } from '../lib/dom.js';

let container = null;

function ensureContainer() {
    if (container && document.body.contains(container)) return container;
    container = el('div', {
        class: 'ui-toast-container',
        'aria-live': 'polite',
        'aria-atomic': 'false',
    });
    document.body.appendChild(container);
    return container;
}

function hide(toast) {
    toast.classList.remove('show');
    toast.classList.add('hiding');
    setTimeout(() => toast.remove(), 300);
}

function render(detail) {
    if (!detail) return;
    const type = ICONS[detail.type] ? detail.type : 'info';
    const closeBtn = el('button', { type: 'button', class: 'ui-toast__close', 'aria-label': '关闭通知' }, [
        el('i', { class: 'bi bi-x' }),
    ]);
    const body = el('div', { class: 'ui-toast__body' }, [
        detail.title ? el('div', { class: 'ui-toast__title', text: detail.title }) : null,
        el('div', { class: 'ui-toast__message', text: detail.message || '' }),
    ]);
    const toast = el('div', { class: `ui-toast ui-toast--${type}`, role: 'alert' }, [
        el('i', { class: `bi ${ICONS[type]} ui-toast__icon`, 'aria-hidden': 'true' }),
        body,
        closeBtn,
    ]);
    closeBtn.addEventListener('click', () => hide(toast));
    ensureContainer().appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('show'));
    setTimeout(() => hide(toast), AUTO_HIDE_MS);
}

document.addEventListener(NOTIFY_EVENT, (e) => render(e.detail));
