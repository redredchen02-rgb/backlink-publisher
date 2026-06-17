/**
 * monitor_hub.js — console monitor hub ("today's anomalies first").
 *
 * Single fail-open fetch to /api/monitor-hub (extends command_center's
 * aggregator). Renders severity-ranked cards: danger cards span full width with
 * the heaviest weight, ok/info collapse into a compact strip. Default is
 * single-load + manual refresh — NO auto-poll (avoids stacking with the existing
 * keep_alive/equity/schedule setInterval pollers). createElement only.
 */
import { fetchJson } from './lib/api.js';
import { renderSkeleton, renderEmpty, renderError } from './ui/states.js';

const grid = document.getElementById('hubGrid');
const refreshBtn = document.getElementById('hubRefresh');

const SEV_ICON = {
    danger: 'bi-exclamation-octagon-fill',
    warning: 'bi-exclamation-triangle-fill',
    ok: 'bi-check-circle-fill',
    info: 'bi-info-circle-fill',
};

function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === 'text') node.textContent = v;
        else if (k === 'class') node.className = v;
        else node.setAttribute(k, v);
    }
    for (const c of children) {
        if (c == null) continue;
        node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
}

function cardEl(card) {
    const sev = SEV_ICON[card.severity] ? card.severity : 'info';
    const head = el('div', { class: 'hub-card__head' }, [
        el('i', { class: `bi ${SEV_ICON[sev]} hub-card__icon`, 'aria-hidden': 'true' }),
        el('span', { class: 'hub-card__title', text: card.title }),
    ]);
    const headline = el('div', { class: 'hub-card__headline', text: card.headline || '' });
    const detail = card.detail ? el('div', { class: 'hub-card__detail', text: card.detail }) : null;

    const footer = el('div', { class: 'hub-card__footer' });
    if (card.deep_link) {
        footer.appendChild(el('a', { class: 'hub-card__deeplink', href: card.deep_link, text: '深钻 →' }));
    }
    if (card.action && card.action.href) {
        footer.appendChild(el('a', { class: 'hub-card__action', href: card.action.href, text: card.action.label || '处理' }));
    }

    return el('div', {
        class: `hub-card hub-card--${sev}`,
        'data-key': card.key,
    }, [head, headline, detail, footer.children.length ? footer : null]);
}

async function load() {
    renderSkeleton(grid, { rows: 4, label: '加载监控数据…' });
    let data;
    try {
        data = await fetchJson('/api/monitor-hub');
    } catch (err) {
        renderError(grid, { title: '加载失败', message: String(err && err.message || err), onRetry: load });
        return;
    }
    if (!data || data.ok === false) {
        renderError(grid, { title: '聚合不可用', message: (data && data.error) || '未知错误', onRetry: load });
        return;
    }
    const cards = data.cards || [];
    if (!cards.length) {
        renderEmpty(grid, { icon: 'bi-check2-circle', title: '今日无异常', message: '所有监控子系统状态正常。' });
        return;
    }
    grid.replaceChildren(...cards.map(cardEl));
}

if (refreshBtn) refreshBtn.addEventListener('click', load);
load();
