// Keep-alive screen entry — native ES module (plan 2026-06-04-001).
//
// Read states (U4): S0 scorecard / S0-empty / S-stale banner.
// Action states (U5): S1 recheck progress (start → poll ~2s → done/cancel).
// Server data arrives once via window.__keepAliveBootstrap; a running recheck
// (tab reopened mid-job, G5a) arrives via window.__keepAliveRunningJob.
// Untrusted strings (target URLs) go through textContent, never innerHTML.

import { qs } from './lib/dom.js';
import { postJson, fetchJson } from './lib/api.js';

const BOOT = window.__keepAliveBootstrap || {};
const RUNNING = window.__keepAliveRunningJob || null;
const TARGETS = BOOT.targets || [];

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

const SVG_NS = 'http://www.w3.org/2000/svg';
const SPARK_W = 64, SPARK_H = 24, SPARK_PAD = 2;

function sparkline(trend) {
  // trend: Array of 4 floats (0–1) or null, oldest first.
  const td = document.createElement('td');
  td.className = 'text-center';
  if (!trend || trend.every(v => v === null)) {
    td.textContent = '—';
    td.className += ' text-muted small';
    return td;
  }

  const n = trend.length;
  const xStep = (SPARK_W - SPARK_PAD * 2) / Math.max(n - 1, 1);
  const points = trend
    .map((v, i) => {
      if (v === null) return null;
      const x = SPARK_PAD + i * xStep;
      const y = SPARK_PAD + (1 - v) * (SPARK_H - SPARK_PAD * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter(Boolean);

  if (points.length < 2) {
    td.textContent = trend[n - 1] !== null ? `${Math.round(trend[n - 1] * 100)}%` : '—';
    td.className += ' text-muted small';
    return td;
  }

  const last = trend.slice().reverse().find(v => v !== null);
  const stroke = last >= 0.8 ? '#34d399' : last >= 0.5 ? '#fbbf24' : '#f87171';

  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('width', SPARK_W);
  svg.setAttribute('height', SPARK_H);
  svg.setAttribute('aria-hidden', 'true');

  const poly = document.createElementNS(SVG_NS, 'polyline');
  poly.setAttribute('points', points.join(' '));
  poly.setAttribute('fill', 'none');
  poly.setAttribute('stroke', stroke);
  poly.setAttribute('stroke-width', '2');
  poly.setAttribute('stroke-linecap', 'round');
  poly.setAttribute('stroke-linejoin', 'round');
  svg.appendChild(poly);
  td.appendChild(svg);
  td.title = trend.map(v => v === null ? '—' : `${Math.round(v * 100)}%`).join(' → ');
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
  tr.appendChild(numCell(`${Math.round((t.strip_rate || 0) * 100)}%`, { muted: !t.needs_attention }));

  const stripped = document.createElement('td');
  stripped.className = 'text-end';
  if (t.stripped > 0) stripped.appendChild(badge('stripped', t.stripped));
  else stripped.textContent = '0';
  tr.appendChild(stripped);

  tr.appendChild(numCell(t.decayed, { muted: t.decayed === 0 }));
  tr.appendChild(numCell(t.check_failed, { muted: t.check_failed === 0 }));
  tr.appendChild(sparkline(t.trend));

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

// ── S1: recheck job (start → poll → progress → done/cancel) ──────────────────
let pollTimer = null;
let activeJobId = null;

function showProgress(show) {
  qs('#recheckProgress').classList.toggle('d-none', !show);
  qs('#recheckBtn').disabled = show;
}

function renderProgress(p) {
  const total = p.total || 0;
  const checked = p.checked || 0;
  const pct = total ? Math.round((checked / total) * 100) : 0;
  const bar = qs('#recheckBar');
  bar.style.width = pct + '%';
  bar.textContent = total ? `${checked}/${total}` : '';
  const vc = p.verdict_counts || {};
  const parts = Object.keys(vc).sort().map((k) => `${k} ${vc[k]}`);
  qs('#recheckLine').textContent = parts.length
    ? `已检查 ${checked}/${total} · ${parts.join(' · ')}`
    : `已检查 ${checked}/${total}`;
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function pollOnce() {
  if (!activeJobId) return;
  let p;
  try {
    p = await fetchJson(`/ce:keep-alive/recheck-status/${activeJobId}`);
  } catch (e) {
    stopPolling();
    activeJobId = null;
    showProgress(false);
    return;
  }
  renderProgress(p);
  if (p.status !== 'running') {
    stopPolling();
    activeJobId = null;
    if (p.status === 'done') {
      window.location.reload();        // fresh verdicts recorded → reload scorecard
    } else {
      showProgress(false);             // cancelled / error → keep current scorecard
    }
  }
}

function beginPolling(jobId) {
  activeJobId = jobId;
  showProgress(true);
  renderProgress({ total: 0, checked: 0, verdict_counts: {} });
  stopPolling();
  pollTimer = setInterval(pollOnce, 2000);
  pollOnce();
}

async function startRecheck() {
  try {
    // 202 (started) and 409 (already running) both return JSON with job_id.
    const resp = await postJson('/ce:keep-alive/recheck', {});
    if (resp && resp.job_id) beginPolling(resp.job_id);
  } catch (e) {
    qs('#recheckLine').textContent = '无法启动巡检：' + (e && e.message ? e.message : '未知错误');
  }
}

async function cancelRecheck() {
  if (!activeJobId) return;
  try {
    await postJson(`/ce:keep-alive/recheck-cancel/${activeJobId}`, {});
  } catch (e) { /* the next poll observes status=cancelled */ }
}

// ── S3–S7: republish flow (select gaps → confirm → publish → auto-recheck) ──
const GAPS = BOOT.gaps || [];
const selected = new Set();
let confirmToken = null;
let rpJobId = null;
let rpTimer = null;

// Shared operator error vocabulary (G1: no raw HTTP/exit codes reach the UI).
const ERROR_VOCAB = {
  non_sticky_platform: '目标平台不在允许的黏性平台内（已拒绝）。',
  missing_targets: '没有选择任何目标。',
};
function mapError(code) {
  const c = String(code || '');
  if (ERROR_VOCAB[c]) return ERROR_VOCAB[c];
  if (c.includes('confirm token')) return '确认令牌无效或已使用，请重新发起。';
  if (c.includes('gap set changed')) return '名单在确认前已变化（有链转为存活），请重新巡检后再试。';
  if (c.includes('already running')) return '已有一个重发任务在进行中，请稍候。';
  if (c.includes('non-sticky')) return '拒绝向非黏性平台重发。';
  return c || '未知错误。';
}

function setBar(sel, frac) {
  qs(sel).style.width = Math.round(Math.max(0, Math.min(1, frac)) * 100) + '%';
}

function gapItem(g) {
  const li = document.createElement('li');
  li.className = 'list-group-item d-flex align-items-center';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'form-check-input me-2';
  cb.dataset.action = 'toggle-gap';
  cb.dataset.target = g.target_url;
  cb.checked = selected.has(g.target_url);
  li.appendChild(cb);
  const span = document.createElement('span');
  span.className = 'target-cell flex-grow-1';
  span.textContent = truncMiddle(g.target_url, 44);
  span.title = g.target_url;
  li.appendChild(span);
  const meta = document.createElement('span');
  meta.className = 'small text-muted ms-2';
  meta.textContent = `剥离 ${g.stripped} · → ${(g.platforms || []).join(', ')}`;
  li.appendChild(meta);
  return li;
}

function updateRepublishBtn() {
  qs('#republishCount').textContent = String(selected.size);
  qs('#republishBtn').disabled = selected.size === 0;
  qs('#gapSelectAll').checked = GAPS.length > 0 && selected.size === GAPS.length;
}

function renderRepublishPanel() {
  // S-stale gates the republish CTA (Unit 4 + Unit 7): never republish off a
  // stale scorecard. Zero gaps → no panel (S2-healthy handles the affirmation).
  if (BOOT.stale || GAPS.length === 0) return;
  qs('#republishPanel').classList.remove('d-none');
  qs('#gapCount').textContent = String(GAPS.length);
  const list = qs('#gapList');
  list.replaceChildren();
  for (const g of GAPS) list.appendChild(gapItem(g));
  const ex = [];
  if (BOOT.live_excluded) ex.push(`${BOOT.live_excluded} 条仍存活已排除`);
  if (BOOT.gap_channel_exhausted) ex.push(`${BOOT.gap_channel_exhausted} 条无可用黏性平台`);
  qs('#gapExcludedLine').textContent = ex.join(' · ');
  updateRepublishBtn();
}

function renderHealthy() {
  if (BOOT.stale || BOOT.is_empty || GAPS.length > 0) return;
  const live = TARGETS.reduce((s, t) => s + (t.live_dofollow || 0), 0);
  const el = qs('#healthyNote');
  el.classList.remove('d-none');
  el.replaceChildren();
  const i = document.createElement('i');
  i.className = 'bi bi-check-circle me-2';
  el.appendChild(i);
  const when = BOOT.last_recheck ? BOOT.last_recheck.replace('T', ' ').slice(0, 16) : '刚刚';
  el.appendChild(document.createTextNode(
    `${live} 条 dofollow 全部存活，无需重发（验证于 ${when}）。`));
}

function toggleGap(target, on) {
  if (on) selected.add(target); else selected.delete(target);
  updateRepublishBtn();
}

function toggleAllGaps(on) {
  selected.clear();
  if (on) for (const g of GAPS) selected.add(g.target_url);
  renderRepublishPanel();
}

function closeConfirm() {
  qs('#confirmOverlay').classList.add('d-none');
  confirmToken = null;
}

function buildConfirmModal(seeds, dropped) {
  const list = qs('#confirmList');
  list.replaceChildren();
  for (const s of seeds) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center';
    const tgt = document.createElement('span');
    tgt.className = 'target-cell';
    tgt.textContent = truncMiddle(s.target_url, 38);
    tgt.title = s.target_url;
    li.appendChild(tgt);
    const arrow = document.createElement('span');
    arrow.className = 'small text-muted ms-2';
    arrow.textContent = '→ ' + s.platform;
    li.appendChild(arrow);
    list.appendChild(li);
  }
  const tgtCount = new Set(seeds.map((s) => s.target_url)).size;
  let msg = `${tgtCount} 个目标页 · ${seeds.length} 条新链`;
  if (dropped.length) msg += ` · ${dropped.length} 条已转存活，自动移除`;
  qs('#confirmCounts').textContent = msg;
  qs('#confirmOverlay').dataset.targets =
    JSON.stringify([...new Set(seeds.map((s) => s.target_url))]);
}

async function openConfirm() {
  if (selected.size === 0) return;
  let tok;
  try {
    tok = await fetchJson('/ce:keep-alive/republish-token');
  } catch (e) {
    flashResult('error', '无法发起重发', '获取确认令牌失败，请重试。');
    return;
  }
  confirmToken = tok.confirm_token;
  // Server truth: only seeds still in the gap set survive; a selected target
  // that went live (not in tok.targets) is dropped and surfaced.
  const serverTargets = new Set(tok.targets || []);
  const seeds = (tok.seeds || []).filter((s) => selected.has(s.target_url));
  const dropped = [...selected].filter((t) => !serverTargets.has(t));
  if (seeds.length === 0) {
    closeConfirm();
    flashResult('ok', '无需重发', '所选的链都已转为存活，请重新巡检确认。');
    return;
  }
  buildConfirmModal(seeds, dropped);
  qs('#confirmOverlay').classList.remove('d-none');
}

async function confirmRepublish() {
  const targets = JSON.parse(qs('#confirmOverlay').dataset.targets || '[]');
  const token = confirmToken;
  closeConfirm();
  if (!targets.length || !token) return;
  let resp;
  try {
    resp = await postJson('/ce:keep-alive/republish', { targets, confirm_token: token });
  } catch (e) {
    flashResult('error', '重发失败', (e && e.message) || '请求出错。');
    return;
  }
  if (resp && resp.job_id) {
    qs('#republishPanel').classList.add('d-none');
    beginRepublishPolling(resp.job_id);
  } else {
    flashResult('error', '重发被拒绝', mapError(resp && resp.error));
  }
}

function renderRepublishProgress(p) {
  const phase = p.phase || 'publishing';
  qs('#republishProgress').classList.remove('d-none');
  if (phase === 'rechecking' || phase === 'done') {
    const done = p.reverify_done || 0;
    const tot = p.reverify_total || 0;
    qs('#republishPhase').textContent = '正在验证新链…';
    setBar('#republishBar', tot ? done / tot : 1);
    qs('#republishLine').textContent = `验证新链 ${done}/${tot}`;
  } else {
    const done = (p.published || 0) + (p.failed || 0);
    const tot = p.total || 0;
    qs('#republishPhase').textContent = '正在重发…';
    setBar('#republishBar', tot ? done / tot : 0);
    qs('#republishLine').textContent = `发布中 ${done}/${tot}`;
  }
}

function fillList(listEl, rows, render) {
  listEl.replaceChildren();
  for (const r of rows) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center small';
    const tgt = document.createElement('span');
    tgt.className = 'target-cell';
    tgt.textContent = truncMiddle(r.target_url, 36);
    tgt.title = r.target_url;
    li.appendChild(tgt);
    const note = document.createElement('span');
    note.className = 'ms-2';
    note.textContent = render(r);
    li.appendChild(note);
    listEl.appendChild(li);
  }
  if (rows.length) listEl.classList.remove('d-none');
}

function renderResult(p) {
  qs('#republishProgress').classList.add('d-none');
  const card = qs('#republishResult');
  card.className = 'card mb-3';
  card.classList.remove('d-none');
  const list = qs('#republishResultList');
  list.replaceChildren();
  list.classList.add('d-none');
  const titleEl = qs('#republishResultTitle');
  const msgEl = qs('#republishResultMsg');

  if (p.state === 'all_success') {
    card.classList.add('border-success');
    titleEl.textContent = '✓ 全部重发并验证存活';
    msgEl.textContent = `${p.confirmed_alive || 0}/${p.reverify_total || 0} 条新链已验证存活。`;
  } else if (p.state === 'partial_success') {
    card.classList.add('border-warning');
    titleEl.textContent = '部分成功';
    msgEl.textContent = `${p.published} 条成功、${p.failed} 条失败；成功的已自动验证存活。`;
    fillList(list, (p.results || []).filter((r) => r.status === 'failed'),
      (r) => '失败：' + mapError(r.error));
  } else if (p.state === 'treadmill') {
    card.classList.add('border-danger');
    titleEl.textContent = '⚠ 新链被平台立即剥离（已停止）';
    msgEl.textContent =
      `${p.restripped} 条新发布的链在验证时已被剥离 — 该黏性平台当前不可靠，已停止，不自动重试。`;
    fillList(list, (p.reverified || []).filter((r) => r.verdict !== 'alive'),
      (r) => '新链已被剥离');
  } else {
    card.classList.add('border-danger');
    titleEl.textContent = '✗ 重发全部失败';
    msgEl.textContent = '没有任何链发布成功。';
    fillList(list, (p.results || []).filter((r) => r.status === 'failed'),
      (r) => '失败：' + mapError(r.error));
  }
}

function flashResult(kind, title, msg) {
  qs('#confirmOverlay').classList.add('d-none');
  qs('#republishProgress').classList.add('d-none');
  const card = qs('#republishResult');
  card.className = 'card mb-3 ' + (kind === 'error' ? 'border-danger' : 'border-secondary');
  card.classList.remove('d-none');
  qs('#republishResultList').classList.add('d-none');
  qs('#republishResultTitle').textContent = title;
  qs('#republishResultMsg').textContent = msg;
}

function stopRpPolling() {
  if (rpTimer) { clearInterval(rpTimer); rpTimer = null; }
}

async function pollRepublishOnce() {
  if (!rpJobId) return;
  let p;
  try {
    p = await fetchJson(`/ce:keep-alive/republish-status/${rpJobId}`);
  } catch (e) {
    stopRpPolling(); rpJobId = null;
    flashResult('error', '重发状态丢失', '无法读取任务状态，请刷新页面。');
    return;
  }
  if (p.status === 'running') { renderRepublishProgress(p); return; }
  stopRpPolling(); rpJobId = null;
  if (p.status === 'error') flashResult('error', '重发任务出错', mapError(p.error));
  else renderResult(p);
}

function beginRepublishPolling(jobId) {
  rpJobId = jobId;
  renderRepublishProgress({ phase: 'publishing', total: 0, published: 0, failed: 0 });
  stopRpPolling();
  rpTimer = setInterval(pollRepublishOnce, 2000);
  pollRepublishOnce();
}

document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;
  if (action === 'recheck') { ev.preventDefault(); startRecheck(); }
  else if (action === 'cancel-recheck') { ev.preventDefault(); cancelRecheck(); }
  else if (action === 'toggle-gap') { toggleGap(el.dataset.target, el.checked); }
  else if (action === 'toggle-all-gaps') { toggleAllGaps(el.checked); }
  else if (action === 'open-confirm') { ev.preventDefault(); openConfirm(); }
  else if (action === 'confirm-republish') { ev.preventDefault(); confirmRepublish(); }
  else if (action === 'cancel-confirm') { ev.preventDefault(); closeConfirm(); }
  else if (action === 'republish-done') { ev.preventDefault(); window.location.reload(); }
});

render(BOOT.is_empty ? 's0-empty' : 's2');
if (!BOOT.is_empty) { renderRepublishPanel(); renderHealthy(); }
// G5a: a recheck still running when the tab was reopened → resume its progress.
if (RUNNING && RUNNING.job_id && RUNNING.status === 'running') {
  beginPolling(RUNNING.job_id);
}
