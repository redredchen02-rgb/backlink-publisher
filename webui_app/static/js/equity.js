// Equity ledger — ES module. Chinese UI, summary stats (U1), platform badges + gap viz (U2),
// preset filters (U3), Fill Gaps action (U4), batch recheck (U5).
// Plan 2026-06-01-007 Unit 5 + 2026-06-05-001.

import { esc, on, qsa } from './lib/dom.js';
import { readCsrf } from './lib/api.js';

const L10N = {
  emptyAll: '暂无目标页面——发布外链以填充台账。',
  emptyFilter: '没有符合当前筛选条件的目标。',
  rechecking: (n, url) => `正在重新检查 ${n} 条记录，涉及 ${url}…`,
  recheckDone: (url, summary) => `${url}: ${summary}（重新检查于 ${new Date().toLocaleTimeString()}）`,
  recheckErr: (url, msg) => `${url}: ${msg}`,
  recheckBtn: '重新检查',
  fillGapBtn: '填补缺口',
  noGap: '无明显缺口',
  gapTitle: '缺口分析',
  gapMissing: (plats) => `缺失平台：${plats}`,
  gapDesired: '建议每个目标至少达到 3 个活跃 dofollow 平台。',
  gapCmdLabel: '终端 CLI 命令（可复制）：',
  gapCopy: '复制',
  gapClose: '关闭',
  gapCopied: '已复制！',
  batchRecheckWeak: '重新检查全部弱目标',
  batchRecheckStale: '重新检查待更新/失败',
  batchRecheckAll: '重新检查所有可见',
  batchProgress: (n, total) => `正在检查 ${n}/${total}…`,
  batchDone: (checked, confirmed, failed, skipped) =>
    `批处理完成：已检查 ${checked} 条，${confirmed} 确认活跃，${failed} 降级失败，${skipped} 跳过`,
  batchNone: '无需处理',
  statsTotal: (n) => `${n}`,
  statsLive: (n) => `${n}`,
  statsWeak: (n) => `${n}`,
  statsHealthy: (pct) => `${pct}%`,
  presetAll: '全部',
  presetNeeds: '需关注',
  presetWeak: '全部弱',
  presetHealthy: '健康',
};

const BOOT = window.__equityLedgerBootstrap || {};
const ROWS = BOOT.rows || [];
const EXACT_THRESHOLD = BOOT.exact_match_threshold;
const STALE_DAYS = BOOT.stale_days;
const LIVE_RANK = { failed: 3, stale: 2, live: 1, unverified: 0 };
let sortKey = 'live_dofollow';
let sortDir = 1;
let activePreset = 'all';

function truncMiddle(s, n = 48) {
  if (s.length <= n) return s;
  const head = Math.ceil(n * 0.6);
  const tail = n - head - 1;
  return s.slice(0, head) + '…' + s.slice(s.length - tail);
}

const _LN = {  
  live: '活跃',
  stale: '待更新',
  failed: '失败',
  unverified: '未验证',
};

function livenessBadge(r) {
  const map = {
    live: ['text-bg-success', 'bi-check-circle', _LN.live],
    stale: ['text-bg-warning', 'bi-clock-history', _LN.stale],
    failed: ['text-bg-danger', 'bi-x-octagon', _LN.failed],
    unverified: ['text-bg-secondary', 'bi-question-circle', _LN.unverified],
  };
  const [cls, icon, label] = map[r.liveness] || map.unverified;
  const date = r.liveness_verified_at
    ? ` <span class="text-muted">${esc(r.liveness_verified_at.slice(0, 10))}</span>` : '';
  const qual = r.liveness_row_level
    ? ' <i class="bi bi-info-circle" title="行级证据"></i>' : '';
  return `<span class="badge ${cls}"><i class="bi ${icon}"></i> ${esc(label)}</span>${date}${qual}`;
}

function exactCell(r) {
  if (!r.has_anchor_data) return '<span class="text-muted">—</span>';
  const pct = (r.exact_match_pct * 100).toFixed(0) + '%';
  const over = EXACT_THRESHOLD != null && r.exact_match_pct > EXACT_THRESHOLD;
  return over ? `<span class="text-danger fw-bold">${pct}</span>` : pct;
}

function liveLabel(r) {
  return (r.live_links === 0 && r.liveness === 'unverified')
    ? `<span class="text-muted">— / ${r.total_links}</span>`
    : `${r.live_links} / ${r.total_links}`;
}

function renderStats(rows) {
  const total = rows.length;
  const liveDofollow = rows.reduce((s, r) => s + (r.live_dofollow || 0), 0);
  const weak = rows.filter((r) => (r.live_dofollow || 0) === 0).length;
  const healthy = total > 0 ? rows.filter((r) => (r.live_dofollow || 0) > 0 && r.liveness === 'live').length : 0;
  const pct = total > 0 ? Math.round((healthy / total) * 100) : 0;

  const bar = document.getElementById('statsBar');
  const inner = document.getElementById('statsInner');
  if (total === 0) { bar.classList.add('d-none'); return; }
  bar.classList.remove('d-none');
  inner.innerHTML =
    `<div class="stat-item stat-total"><div class="stat-value">${L10N.statsTotal(total)}</div><div class="stat-label">目标</div></div>` +
    `<div class="stat-item stat-live"><div class="stat-value">${L10N.statsLive(liveDofollow)}</div><div class="stat-label">有效 dofollow</div></div>` +
    `<div class="stat-item stat-weak"><div class="stat-value">${L10N.statsWeak(weak)}</div><div class="stat-label">弱目标</div></div>` +
    `<div class="stat-item stat-healthy"><div class="stat-value">${L10N.statsHealthy(pct)}</div><div class="stat-label">健康率</div></div>`;
}

function presetFilter(rows, preset) {
  if (preset === 'all') return rows;
  if (preset === 'needs-attention')
    return rows.filter((r) => (r.live_dofollow || 0) === 0 && (r.liveness === 'failed' || r.liveness === 'stale'));
  if (preset === 'weak') return rows.filter((r) => (r.live_dofollow || 0) === 0);
  if (preset === 'healthy') return rows.filter((r) => (r.live_dofollow || 0) > 0 && r.liveness === 'live');
  return rows;
}

function updatePresetChips() {
  let needsCount = 0, weakCount = 0, healthyCount = 0;
  for (const r of ROWS) {
    const ld = r.live_dofollow || 0;
    if (ld === 0 && (r.liveness === 'failed' || r.liveness === 'stale')) needsCount++;
    if (ld === 0) weakCount++;
    if (ld > 0 && r.liveness === 'live') healthyCount++;
  }
  const pcAll = document.getElementById('pcAll');
  const pcNeeds = document.getElementById('pcNeeds');
  const pcWeak = document.getElementById('pcWeak');
  const pcHealthy = document.getElementById('pcHealthy');
  if (pcAll) pcAll.textContent = ROWS.length;
  if (pcNeeds) pcNeeds.textContent = needsCount;
  if (pcWeak) pcWeak.textContent = weakCount;
  if (pcHealthy) pcHealthy.textContent = healthyCount;
}

function passesFilter(r, lf, uf) {
  if (uf && !r.target_url.toLowerCase().includes(uf)) return false;
  if (lf === 'all') return true;
  if (lf === 'has-failed') return r.liveness === 'failed';
  if (lf === 'has-stale') return r.liveness === 'stale';
  return r.liveness === lf;
}

function detailRowHTML(r) {
  const d = r.dofollow || {};
  const platforms = r.platforms || [];
  const liveDofollowPlats = r.live_dofollow_platforms || [];
  const missingPlats = r.missing_dofollow_platforms || [];
  const ldfSet = new Set(liveDofollowPlats);

  let platHtml = platforms.length
    ? platforms.map((p) => {
        const cls = ldfSet.has(p) ? 'live' : 'stale';
        return `<span class="platform-badge ${cls}">${esc(p)}</span>`;
      }).join('')
    : '<span class="text-muted">—</span>';

  let gapHtml = '';
  if (missingPlats.length > 0) {
    gapHtml = `<div class="gap-line"><i class="bi bi-exclamation-triangle"></i> 缺失: ${esc(missingPlats.join(', '))}</div>`;
  } else if (platforms.length > 0) {
    gapHtml = `<div class="gap-line text-success"><i class="bi bi-check-circle"></i> ${L10N.noGap}</div>`;
  }

  const fillBtn = (r.live_dofollow || 0) === 0
    ? `<button class="btn btn-sm btn-outline-danger mt-1 fill-gaps">${L10N.fillGapBtn}</button>`
    : '';

  return `<td></td><td colspan="8">
    <table class="matrix"><tr>
      <th>dofollow</th><td>${d.dofollow || 0}</td>
      <th>uncertain</th><td>${d.uncertain || 0}</td>
      <th>nofollow</th><td>${d.nofollow || 0} (高 ${d.nofollow_high || 0} / 低 ${d.nofollow_low || 0})</td>
      <th>unknown</th><td>${d.unknown || 0}</td>
    </tr></table>
    <div class="mt-1"><strong>平台：</strong>${platHtml}</div>
    ${gapHtml}
    <div class="mt-1">${fillBtn}</div>
  </td>`;
}

function render() {
  const lf = document.getElementById('livenessFilter').value;
  const uf = document.getElementById('urlFilter').value.trim().toLowerCase();

  let rows = presetFilter(ROWS, activePreset);
  rows = rows.filter((r) => passesFilter(r, lf, uf));
  rows.sort((a, b) => {
    let av = a[sortKey];
    let bv = b[sortKey];
    if (sortKey === 'liveness') { av = LIVE_RANK[av]; bv = LIVE_RANK[bv]; }
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return a.target_url < b.target_url ? -1 : 1;
  });

  const body = document.getElementById('ledgerBody');
  const empty = document.getElementById('emptyState');
  const batchBar = document.getElementById('batchBar');
  body.innerHTML = '';
  if (ROWS.length === 0) {
    empty.textContent = L10N.emptyAll;
    empty.classList.remove('d-none');
    if (batchBar) batchBar.classList.add('d-none');
    renderStats([]);
    return;
  }
  if (rows.length === 0) {
    empty.textContent = L10N.emptyFilter;
    empty.classList.remove('d-none');
    if (batchBar) batchBar.classList.add('d-none');
    renderStats(ROWS);
    return;
  }
  empty.classList.add('d-none');
  if (batchBar) batchBar.classList.remove('d-none');

  const hasWeak = rows.some((r) => (r.live_dofollow || 0) === 0);
  const hasStale = rows.some((r) => r.liveness === 'stale' || r.liveness === 'failed');
  const weakBtn = document.getElementById('batchRecheckWeak');
  const staleBtn = document.getElementById('batchRecheckStale');
  if (weakBtn) weakBtn.style.display = hasWeak ? '' : 'none';
  if (staleBtn) staleBtn.style.display = hasStale ? '' : 'none';

  for (const r of rows) {
    const tr = document.createElement('tr');
    if (r.live_dofollow === 0) tr.className = 'row-weak';
    tr.innerHTML =
      `<td><button class="btn btn-sm btn-link p-0 expand" aria-expanded="false" title="详情"><i class="bi bi-chevron-right"></i></button></td>` +
      `<td class="target-cell" title="${esc(r.target_url)}">${esc(truncMiddle(r.target_url))}</td>` +
      `<td class="text-end">${liveLabel(r)}</td>` +
      `<td class="text-end fw-semibold">${r.live_dofollow}</td>` +
      `<td class="text-end small">${(r.dofollow || {}).dofollow || 0}<span class="text-muted">/</span>${(r.dofollow || {}).uncertain || 0}<span class="text-muted">/</span>${(r.dofollow || {}).nofollow || 0}<span class="text-muted">/</span>${(r.dofollow || {}).unknown || 0}</td>` +
      `<td class="text-end">${exactCell(r)}</td>` +
      `<td class="text-end">${r.platform_count}</td>` +
      `<td>${livenessBadge(r)}</td>` +
      `<td><button class="btn btn-sm btn-outline-primary recheck" ${r.history_item_ids.length ? '' : 'disabled'}>${L10N.recheckBtn}</button></td>`;
    body.appendChild(tr);

    const detail = document.createElement('tr');
    detail.className = 'detail-row d-none';
    detail.innerHTML = detailRowHTML(r);
    body.appendChild(detail);

    on(tr.querySelector('.expand'), 'click', (e) => {
      const btn = e.currentTarget;
      const open = detail.classList.toggle('d-none') === false;
      btn.setAttribute('aria-expanded', String(open));
      btn.querySelector('i').className = open ? 'bi bi-chevron-down' : 'bi bi-chevron-right';
    });
    on(tr.querySelector('.recheck'), 'click', () => recheck(r, tr));
    const fillBtn = detail.querySelector('.fill-gaps');
    if (fillBtn) on(fillBtn, 'click', () => fillGaps(r));
  }

  renderStats(rows);
}

let recheckBusy = false;
async function recheck(r, tr) {
  if (recheckBusy) return;
  recheckBusy = true;
  const btn = tr.querySelector('.recheck');
  const status = document.getElementById('recheckStatus');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
  status.textContent = L10N.rechecking(r.history_item_ids.length, r.target_url);
  try {
    const resp = await fetch('/ce:equity-ledger/recheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
      body: JSON.stringify({ target_url: r.target_url, stale_days: STALE_DAYS }),
    });
    const ct = resp.headers.get('content-type') || '';
    if (!resp.ok || !ct.includes('application/json')) throw new Error('重新检查失败 (' + resp.status + ')');
    const data = await resp.json();
    Object.assign(r, data.row);
    const i = ROWS.findIndex((x) => x.target_url === r.target_url);
    if (i >= 0) Object.assign(ROWS[i], data.row);
    rerenderRowInPlace(r, tr);
    status.textContent = L10N.recheckDone(r.target_url, data.summary);
  } catch (err) {
    status.textContent = L10N.recheckErr(r.target_url, err.message);
    btn.disabled = false;
    btn.textContent = L10N.recheckBtn;
  } finally {
    recheckBusy = false;
  }
}

function rerenderRowInPlace(r, tr) {
  const cells = tr.children;
  cells[2].innerHTML = liveLabel(r);
  cells[3].textContent = r.live_dofollow;
  cells[7].innerHTML = livenessBadge(r);
  tr.classList.toggle('row-weak', r.live_dofollow === 0);
  const btn = tr.querySelector('.recheck');
  btn.disabled = r.history_item_ids.length === 0;
  btn.textContent = L10N.recheckBtn;
}

let gapModalOverlay = null;

async function fillGaps(r) {
  try {
    const resp = await fetch('/ce:equity-ledger/fill-gaps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
      body: JSON.stringify({ target_url: r.target_url }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '缺口分析失败');
    showGapModal(r.target_url, data);
  } catch (err) {
    const status = document.getElementById('recheckStatus');
    if (status) status.textContent = L10N.recheckErr(r.target_url, err.message);
  }
}

function showGapModal(targetUrl, data) {
  if (gapModalOverlay) gapModalOverlay.remove();

  const missing = data.missing_platforms || [];
  const cli = data.cli_command || '';
  const deficiency = data.deficiency || 0;

  gapModalOverlay = document.createElement('div');
  gapModalOverlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1060;display:flex;align-items:center;justify-content:center;';
  const panel = document.createElement('div');
  panel.style.cssText = 'background:#fff;border-radius:16px;max-width:540px;width:90%;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,.3);max-height:80vh;overflow-y:auto;';
  panel.innerHTML =
    `<h5 class="mb-2"><i class="bi bi-exclamation-triangle text-danger me-1"></i>${L10N.gapTitle}</h5>` +
    `<p class="small text-muted mb-2">目标：<code class="small">${esc(targetUrl)}</code></p>` +
    `<p><strong>${L10N.gapMissing(missing.join(', '))}</strong></p>` +
    `<p class="small text-muted">${L10N.gapDesired} 当前缺口：${deficiency}</p>` +
    (cli ? `<div class="mb-2"><label class="small text-muted">${L10N.gapCmdLabel}</label>` +
      `<div class="d-flex"><code id="gapCliCode" class="small p-2 bg-light rounded flex-fill" style="word-break:break-all;">${esc(cli)}</code>` +
      `<button class="btn btn-sm btn-outline-secondary ms-1" id="gapCopyBtn">${L10N.gapCopy}</button></div></div>` : '') +
    `<div class="text-end mt-3"><button class="btn btn-sm btn-secondary" id="gapCloseBtn">${L10N.gapClose}</button></div>`;
  gapModalOverlay.appendChild(panel);
  document.body.appendChild(gapModalOverlay);

  on(document.getElementById('gapCloseBtn'), 'click', () => { gapModalOverlay.remove(); gapModalOverlay = null; });
  on(gapModalOverlay, 'click', (e) => { if (e.target === gapModalOverlay) { gapModalOverlay.remove(); gapModalOverlay = null; } });

  const copyBtn = document.getElementById('gapCopyBtn');
  if (copyBtn) {
    on(copyBtn, 'click', async () => {
      try {
        await navigator.clipboard.writeText(cli);
        copyBtn.textContent = L10N.gapCopied;
        setTimeout(() => { copyBtn.textContent = L10N.gapCopy; }, 2000);
      } catch { /* clipboard not available */ }
    });
  }
}

let batchJobId = null;
let batchPollTimer = null;

async function startBatchRecheck(filter) {
  const progress = document.getElementById('batchProgress');
  const progressText = document.getElementById('batchProgressText');
  const status = document.getElementById('recheckStatus');
  if (batchPollTimer) { clearInterval(batchPollTimer); batchPollTimer = null; }

  progress.classList.remove('d-none');
  progressText.textContent = L10N.batchProgress(0, '…');
  if (status) status.textContent = '';

  try {
    const resp = await fetch('/ce:equity-ledger/batch-recheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
      body: JSON.stringify({ filter }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || '批量操作启动失败');
    batchJobId = data.job_id;

    batchPollTimer = setInterval(() => pollBatchStatus(), 2000);
  } catch (err) {
    progress.classList.add('d-none');
    if (status) status.textContent = `批量操作错误：${err.message}`;
  }
}

async function pollBatchStatus() {
  if (!batchJobId) return;
  try {
    const resp = await fetch(`/ce:equity-ledger/batch-recheck/${batchJobId}/status`);
    if (resp.status === 404) { stopBatchPolling(); return; }
    const data = await resp.json();
    const progress = document.getElementById('batchProgress');
    const progressText = document.getElementById('batchProgressText');
    if (progressText) progressText.textContent = L10N.batchProgress(data.checked, data.total || '?');

    if (data.done) {
      stopBatchPolling();
      progress.classList.add('d-none');
      const status = document.getElementById('recheckStatus');
      if (data.checked > 0) {
        if (status) status.textContent = L10N.batchDone(data.checked, data.confirmed, data.failed, data.skipped);
        render();
      } else {
        if (status) status.textContent = L10N.batchNone;
      }
    }
  } catch { stopBatchPolling(); }
}

function stopBatchPolling() {
  if (batchPollTimer) { clearInterval(batchPollTimer); batchPollTimer = null; }
  batchJobId = null;
}

function boot() {
  qsa('th[data-sort]').forEach((th) => on(th, 'click', () => {
    const k = th.dataset.sort;
    sortDir = (sortKey === k) ? -sortDir : 1;
    sortKey = k;
    qsa('th[data-sort]').forEach((h) => h.removeAttribute('aria-sort'));
    th.setAttribute('aria-sort', sortDir === 1 ? 'ascending' : 'descending');
    render();
  }));

  qsa('#presetFilters .preset-chip').forEach((chip) => on(chip, 'click', () => {
    qsa('#presetFilters .preset-chip').forEach((c) => c.classList.remove('active'));
    chip.classList.add('active');
    activePreset = chip.dataset.preset;
    render();
  }));

  const lf = document.getElementById('livenessFilter');
  const uf = document.getElementById('urlFilter');
  if (lf) on(lf, 'change', render);
  if (uf) on(uf, 'input', render);

  const bw = document.getElementById('batchRecheckWeak');
  const bs = document.getElementById('batchRecheckStale');
  const ba = document.getElementById('batchRecheckAll');
  if (bw) on(bw, 'click', () => startBatchRecheck('weak'));
  if (bs) on(bs, 'click', () => startBatchRecheck('stale-failed'));
  if (ba) on(ba, 'click', () => startBatchRecheck('all'));

  updatePresetChips();
  render();
}

if (document.readyState === 'loading') on(document, 'DOMContentLoaded', boot); else boot();
