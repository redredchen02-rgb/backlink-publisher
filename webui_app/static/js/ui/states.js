/**
 * ui/states.js — shared empty / loading / error state renderers (console style).
 *
 * Every renderer clears its container and rebuilds it with createElement only —
 * no untrusted text ever touches innerHTML (frontend anti-rot rule). Callback
 * buttons (onAction/onRetry) bind via addEventListener on the element we created,
 * never an inline on* handler. Styles live in components.css.
 */

// el() — local createElement builder mirroring the one in notifications.js.
// props.text -> textContent; props.class -> className; other keys -> attributes.
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
 * Loading skeleton. Replaces container content with shimmer bars.
 * @param {HTMLElement} container
 * @param {{rows?: number, label?: string}} [opts]
 */
export function renderSkeleton(container, opts = {}) {
    if (!container) return;
    const { rows = 3, label = '加载中…' } = opts;
    container.replaceChildren();
    const wrap = el('div', { class: 'ui-skeleton', role: 'status', 'aria-busy': 'true', 'aria-label': label });
    for (let i = 0; i < Math.max(1, rows); i++) {
        wrap.appendChild(el('div', { class: 'ui-skeleton__bar' }));
    }
    container.appendChild(wrap);
}

/**
 * Empty state with optional call-to-action.
 * @param {HTMLElement} container
 * @param {{icon?: string, title?: string, message?: string, actionLabel?: string, onAction?: Function}} [opts]
 */
export function renderEmpty(container, opts = {}) {
    if (!container) return;
    const { icon = 'bi-inbox', title = '暂无数据', message = '', actionLabel = '', onAction = null } = opts;
    container.replaceChildren();
    const children = [
        el('i', { class: `bi ${icon} ui-empty__icon`, 'aria-hidden': 'true' }),
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

/**
 * Error state with optional retry. Does not assert success; the caller decides
 * the message. Retry button re-invokes onRetry (which typically re-renders).
 * @param {HTMLElement} container
 * @param {{title?: string, message?: string, retryLabel?: string, onRetry?: Function}} [opts]
 */
export function renderError(container, opts = {}) {
    if (!container) return;
    const { title = '出错了', message = '', retryLabel = '重试', onRetry = null } = opts;
    container.replaceChildren();
    const children = [
        el('i', { class: 'bi bi-exclamation-octagon ui-error__icon', 'aria-hidden': 'true' }),
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
