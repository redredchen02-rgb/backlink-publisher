// Keep-alive screen entry — native ES module (plan 2026-06-04-001 Unit 4 / R3).
//
// Read-only scorecard states: S0 (scorecard), S0-empty (no recheck yet),
// S-stale (overlay banner). The single-screen state controller (render(state))
// is established here; Units 5-7 add the action states (S1 recheck progress,
// S3-S7 republish) as new cases on this same switch — no new routes.
//
// Server data arrives once via window.__keepAliveBootstrap (an external module
// cannot read the Jinja context). Untrusted strings (target URLs) go through
// textContent / esc, never innerHTML.

import { esc, qs } from './lib/dom.js';

const BOOT = window.__keepAliveBootstrap || {};
const TARGETS = BOOT.targets || [];

// New liveness states carry a non-color signifier (icon + label) so stripped
// (republishable) is distinguishable from check-failed (do nothing) without
// relying on colour — the screen's most consequential distinction.
const BADGES = {
  stripped: ['text-bg-danger', 'bi-scissors', '已剥离'],
  decayed: ['text-bg-secondary', 'bi-arrow-down-circle', '降级'],
  check_failed: ['text-bg-light text-dark', 'bi-question-circle', '检查失败'],
  alive: ['text-bg-success', 'bi-check-circle', '存活'],
};

function truncMiddle(s, n = 52) {
  if (!s || s.length <= n) return s || '';
  const head = Math.ceil(n * 0.6);
  return s.slice(0, head) + '…' + s.slice(s.length - (n - head - 1));
}

function badge(kind, count) {
  const [cls, icon, label] = BADGES[kind];
  const span = document.createElement('span');
  span.className = `badge ka-badge ${cls} me-1`;
  const i = document.createElement('i');
  i.className = `bi ${icon} me-1`;
  span.appendChild(i);
  span.appendChild(document.createTextNode(`${label} ${count}`));
  return span;
}

function numCell(value, { strong = false, muted = false } = {}) {
  const td = document.createElement('td');
  td.className = 'text-end' + (muted ? ' text-muted' : '');
  td.textContent = String(value);
  if (strong) td.style.fontWeight = '600';
  return td;
}

function targetRow(t) {
  const tr = document.createElement('tr');
  if (t.needs_attention) tr.className = 'ka-attention';

  const tgt = document.createElement('td');
  tgt.className = 'target-cell';
  tgt.textContent = truncMiddle(t.target_url);
  tgt.title = t.target_url;
  tr.appendChild(tgt);

  tr.appendChild(numCell(t.live_dofollow, { strong: true }));
  tr.appendChild(numCell(`${Math.round((t.strip_rate || 0) * 100)}%`,
    { muted: !t.needs_attention }));

  const stripped = document.createElement('td');
  stripped.className = 'text-end';
  if (t.stripped > 0) stripped.appendChild(badge('stripped', t.stripped));
  else stripped.textContent = '0';
  tr.appendChild(stripped);

  tr.appendChild(numCell(t.decayed, { muted: t.decayed === 0 }));
  tr.appendChild(numCell(t.check_failed, { muted: t.check_failed === 0 }));

  const plats = document.createElement('td');
  plats.className = 'small text-muted';
  plats.textContent = (t.platforms || []).join(', ');
  tr.appendChild(plats);

  const lv = document.createElement('td');
  lv.className = 'small text-muted';
  lv.textContent = t.last_verified ? t.last_verified.replace('T', ' ').slice(0, 16) : '—';
  tr.appendChild(lv);

  return tr;
}

function renderScorecard() {
  const body = qs('#keepAliveBody');
  body.replaceChildren();
  let lastGroup = null;
  for (const t of TARGETS) {
    const group = t.needs_attention ? 'attention' : 'healthy';
    if (group !== lastGroup) {
      const label = document.createElement('tr');
      label.className = 'ka-section-label';
      const td = document.createElement('td');
      td.colSpan = 8;
      td.textContent = group === 'attention' ? '需要关注（有被剥离的链）' : '健康';
      label.appendChild(td);
      body.appendChild(label);
      lastGroup = group;
    }
    body.appendChild(targetRow(t));
  }
  const fresh = qs('#freshnessLine');
  if (BOOT.last_recheck) {
    const days = BOOT.stale_days;
    fresh.textContent = `最近巡检 ${BOOT.last_recheck.replace('T', ' ').slice(0, 16)}`
      + (days ? `（约 ${days} 天前）` : '') + ' · 按 strip 率排序，流血目标在前';
  }
}

function renderStaleBanner() {
  if (!BOOT.stale) return;
  const el = qs('#staleBanner');
  el.classList.remove('d-none');
  el.replaceChildren();
  const i = document.createElement('i');
  i.className = 'bi bi-exclamation-triangle me-2';
  el.appendChild(i);
  const days = BOOT.stale_days != null ? `${BOOT.stale_days} 天前` : '更早';
  el.appendChild(document.createTextNode(
    `看板已过期：有比上次巡检（${days}）更新的发布尚未验证。操作前请先「立即巡检」。`));
}

function renderEmpty() {
  const el = qs('#emptyState');
  el.classList.remove('d-none');
  el.replaceChildren();
  const h = document.createElement('p');
  h.className = 'h5 mb-2';
  h.textContent = '尚未检查过保活状态';
  const sub = document.createElement('p');
  sub.textContent = '「立即巡检」会逐条复查已发布的外链，看哪些还活着、哪些被剥离。';
  el.appendChild(h);
  el.appendChild(sub);
}

// Single-screen state controller. U5-U7 add cases (s1-rechecking, s3-review,
// s4-confirm, s5-republishing, s6, s7) — exactly one primary panel visible.
function render(state) {
  for (const id of ['#emptyState', '#scorecard']) qs(id).classList.add('d-none');
  if (state === 's0-empty') {
    renderEmpty();
  } else {
    qs('#scorecard').classList.remove('d-none');
    renderStaleBanner();
    renderScorecard();
  }
}

render(BOOT.is_empty ? 's0-empty' : 's2');
