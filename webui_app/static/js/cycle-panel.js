// Automated keepalive cycle status panel (R8 / plan 2026-06-08-001).
//
// Self-contained ES module: fetches /ce:keep-alive/cycle-status, renders the
// #cyclePanel, and handles reset-exhausted interactions.
// Exported: loadCyclePanel() called by keep_alive.js at module init.
//
// All strings via textContent — never innerHTML with untrusted content.
// POST uses postJson() for automatic CSRF + Content-Type handling.
// readCsrf() is NOT needed directly here; postJson() calls it internally.

import { postJson, fetchJson } from './lib/api.js';

function qs(sel, ctx = document) { return ctx.querySelector(sel); }

function truncMiddle(s, n = 52) {
  if (!s || s.length <= n) return s || '';
  const head = Math.ceil(n * 0.6);
  return s.slice(0, head) + '…' + s.slice(s.length - (n - head - 1));
}

function formatLastRun(isoStr) {
  if (!isoStr) return '—';
  try {
    // Display in browser local time (launchd fires at 06:30 local; UTC would confuse).
    const d = new Date(isoStr);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
         + `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch (_) {
    return isoStr.slice(0, 16).replace('T', ' ');
  }
}

const SUMMARY_LABELS = {
  gaps_found:         '找到缺口',
  published:          '已发布',
  reverified_alive:   '重验存活',
  reverified_dead:    '重验已死',
  exhausted_skipped:  '跳过(耗尽)',
};

function renderSummaryDl(summary) {
  const dl = qs('#cycleSummaryDl');
  dl.replaceChildren();
  for (const [key, label] of Object.entries(SUMMARY_LABELS)) {
    const col = document.createElement('div');
    col.className = 'col';
    const dt = document.createElement('dt');
    dt.className = 'text-muted small mb-0';
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.className = 'fw-semibold mb-0';
    dd.textContent = String(summary[key] ?? 0);
    col.appendChild(dt);
    col.appendChild(dd);
    dl.appendChild(col);
  }
}

function renderPlatforms(platforms) {
  const section = qs('#cyclePlatformSection');
  if (!platforms || platforms.length === 0) {
    section.classList.add('d-none');
    return;
  }
  const tbody = qs('#cyclePlatformBody');
  tbody.replaceChildren();
  for (const p of platforms) {
    const tr = document.createElement('tr');

    const tdName = document.createElement('td');
    tdName.textContent = p.name;
    tr.appendChild(tdName);

    const tdWeight = document.createElement('td');
    tdWeight.className = 'text-end';
    tdWeight.textContent = p.weight.toFixed(4);
    tr.appendChild(tdWeight);

    const tdStatus = document.createElement('td');
    if (p.locked) {
      const badge = document.createElement('span');
      badge.className = 'badge text-bg-secondary cycle-badge-locked';
      badge.textContent = '已锁定';
      tdStatus.appendChild(badge);
    } else if (p.circuit_broken) {
      const badge = document.createElement('span');
      badge.className = 'badge text-bg-danger cycle-badge-broken';
      badge.textContent = '熔断';
      tdStatus.appendChild(badge);
    } else {
      tdStatus.textContent = '—';
    }
    tr.appendChild(tdStatus);

    const tdAlive = document.createElement('td');
    tdAlive.className = 'text-end text-muted';
    tdAlive.textContent = String(p.alive_count ?? 0);
    tr.appendChild(tdAlive);

    const tdTotal = document.createElement('td');
    tdTotal.className = 'text-end text-muted';
    tdTotal.textContent = String(p.total_published ?? 0);
    tr.appendChild(tdTotal);

    tbody.appendChild(tr);
  }
  section.classList.remove('d-none');
}

function renderExhausted(exhausted, exhaustedTotal) {
  const section = qs('#cycleExhaustedSection');
  const list = qs('#cycleExhaustedList');
  const truncNote = qs('#cycleExhaustedTruncNote');
  list.replaceChildren();

  if (!exhausted || exhausted.length === 0) {
    section.classList.add('d-none');
    return;
  }

  if (exhaustedTotal > exhausted.length) {
    truncNote.textContent =
      `（显示 ${exhausted.length} / ${exhaustedTotal} 个，其余请用 keepalive-status CLI 查看）`;
    truncNote.classList.remove('d-none');
  } else {
    truncNote.classList.add('d-none');
  }

  for (const e of exhausted) {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex align-items-center justify-content-between py-1';

    const info = document.createElement('div');
    const urlSpan = document.createElement('span');
    urlSpan.className = 'font-monospace small me-2';
    urlSpan.textContent = truncMiddle(e.target_url, 44);
    urlSpan.title = e.target_url;
    info.appendChild(urlSpan);

    const attBadge = document.createElement('span');
    attBadge.className = 'badge text-bg-secondary me-1';
    attBadge.textContent = `${e.attempts} 次`;
    info.appendChild(attBadge);

    if (e.last_outcome) {
      const outBadge = document.createElement('span');
      outBadge.className = 'badge text-bg-light text-dark small';
      outBadge.textContent = e.last_outcome;
      info.appendChild(outBadge);
    }
    li.appendChild(info);

    const btn = document.createElement('button');
    btn.className = 'btn btn-outline-warning btn-sm ms-2';
    btn.dataset.action = 'reset-exhausted';
    btn.dataset.targetUrl = e.target_url;
    btn.textContent = '重置';
    li.appendChild(btn);

    list.appendChild(li);
  }
  section.classList.remove('d-none');
}

let _pendingResetUrl = null;

function showResetConfirm(targetUrl) {
  _pendingResetUrl = targetUrl;
  qs('#cycleResetTargetText').textContent = targetUrl;
  const overlay = qs('#cycleResetConfirm');
  overlay.classList.remove('d-none');
  qs('#cycleResetConfirmBtn').disabled = false;
  qs('#cycleResetConfirmBtn').focus();
}

function hideResetConfirm() {
  _pendingResetUrl = null;
  qs('#cycleResetConfirm').classList.add('d-none');
}

function showError(msg) {
  const el = qs('#cycleError');
  el.textContent = msg;
  el.classList.remove('d-none');
  setTimeout(() => el.classList.add('d-none'), 8000);
}

export async function loadCyclePanel() {
  const refreshBtn = qs('#cyclePanelRefresh');
  if (refreshBtn) refreshBtn.disabled = true;

  try {
    let data;
    try {
      data = await fetchJson('/ce:keep-alive/cycle-status');
    } catch (e) {
      qs('#cycleLoading').classList.add('d-none');
      showError('无法加载周期状态：' + (e && e.message ? e.message : '网络错误'));
      return;
    }

    qs('#cycleLoading').classList.add('d-none');
    qs('#cycleError').classList.add('d-none');

    if (!data.has_data) {
      const el = qs('#cycleEmpty');
      el.textContent = '暂无自动周期记录。请确认 launchd plist 已加载（每日 06:30）。';
      el.classList.remove('d-none');
      qs('#cycleContent').classList.add('d-none');
      return;
    }

    qs('#cycleEmpty').classList.add('d-none');
    qs('#cycleLastRun').textContent = '上次运行：' + formatLastRun(data.last_run_at);
    renderSummaryDl(data.cycle_summary || {});
    renderPlatforms(data.platforms || []);
    renderExhausted(data.exhausted || [], data.exhausted_total || 0);
    qs('#cycleContent').classList.remove('d-none');
  } finally {
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

async function doReset(targetUrl) {
  const confirmBtn = qs('#cycleResetConfirmBtn');
  confirmBtn.disabled = true;
  try {
    const resp = await postJson('/ce:keep-alive/reset-exhausted', { target_url: targetUrl });
    hideResetConfirm();
    if (resp && resp.was_present === false) {
      showError('此目标已不在清单中（可能已被其他方式重置）。');
    }
    // Re-fetch regardless so the panel reflects current state.
    qs('#cycleLoading').classList.remove('d-none');
    qs('#cycleContent').classList.add('d-none');
    qs('#cycleEmpty').classList.add('d-none');
    await loadCyclePanel();
  } catch (e) {
    confirmBtn.disabled = false;
    hideResetConfirm();
    showError('重置失败：' + (e && e.message ? e.message : '未知错误'));
  }
}

// Delegated listener scoped to the cycle panel area + reset confirm modal.
document.addEventListener('click', (ev) => {
  const el = ev.target.closest('[data-action]');
  if (!el) return;
  const action = el.dataset.action;

  if (action === 'refresh-cycle') {
    ev.preventDefault();
    qs('#cycleLoading').classList.remove('d-none');
    qs('#cycleContent').classList.add('d-none');
    qs('#cycleEmpty').classList.add('d-none');
    loadCyclePanel();
  } else if (action === 'reset-exhausted') {
    ev.preventDefault();
    showResetConfirm(el.dataset.targetUrl);
  } else if (action === 'confirm-reset-exhausted') {
    ev.preventDefault();
    if (_pendingResetUrl) doReset(_pendingResetUrl);
  } else if (action === 'cancel-reset-exhausted') {
    ev.preventDefault();
    hideResetConfirm();
  }
});

// Close reset confirm on Escape.
document.addEventListener('keydown', (ev) => {
  if (ev.key === 'Escape' && _pendingResetUrl) hideResetConfirm();
});

// Auto-load on DOMContentLoaded (or immediately if already loaded).
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', loadCyclePanel);
} else {
  loadCyclePanel();
}
