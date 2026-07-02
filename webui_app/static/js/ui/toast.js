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
 *
 * Plan 2026-07-01-002 Unit 5: when detail.reportId is present (an
 * auto-captured error that was persisted server-side, bridged in via
 * notifications.js's bindErrorCaptureBridge()), this renders an extra
 * "补充说明" (add detail) action that dispatches app:report-detail-request —
 * ui/error-report-entry.js listens for that and opens its panel pre-filled
 * with the reportId, PATCHing it on submit. A reportId-bearing toast is also
 * sticky (skips the AUTO_HIDE_MS timer below): a "add more detail" action
 * that vanishes after 5s would defeat its own purpose. Both behaviours are
 * gated on detail.reportId alone — an ordinary toast is unaffected.
 */
const NOTIFY_EVENT = 'app:notify';

// app:report-detail-request — dispatched when a reportId-bearing toast's
// "补充说明" action is clicked; carries {reportId}. Kept as a literal (not
// imported), for the same decoupling reason NOTIFY_EVENT above stays a
// literal rather than importing it from notifications.js: this module must
// stay independently loadable regardless of which listener module (if any)
// is present, or its script tag order. Keep this string in sync with
// ui/error-report-entry.js.
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
    const hasReportId = !!detail.reportId;

    const closeBtn = el('button', { type: 'button', class: 'ui-toast__close', 'aria-label': '关闭通知' }, [
        el('i', { class: 'bi bi-x' }),
    ]);

    // Only a reportId-bearing toast gets the "补充说明" action — see the
    // module docstring's Unit 5 note. Paired: no reportId -> no action.
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
    // A reportId-bearing toast is sticky — it must stay reachable until the
    // user acts on it (or manually closes it via closeBtn above), not vanish
    // on its own. An ordinary toast keeps the existing 5s auto-hide.
    if (!hasReportId) {
        setTimeout(() => hide(toast), AUTO_HIDE_MS);
    }
}

document.addEventListener(NOTIFY_EVENT, (e) => render(e.detail));
