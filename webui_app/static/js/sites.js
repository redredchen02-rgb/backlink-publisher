// Sites page module — quick-publish + batch operations.
import { fetchJson, postJson } from './lib/api.js';

// ── Quick-publish ──────────────────────────────────────────────────────────

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action="quick-publish"]');
  if (!btn) return;

  const defaultsUrl = btn.dataset.defaultsUrl;
  const quickUrl    = btn.dataset.quickUrl;
  const fallbackUrl = btn.dataset.fallbackUrl;

  const label   = btn.querySelector('.quick-publish-label');
  const spinner = btn.querySelector('.quick-publish-spinner');

  label.classList.add('d-none');
  spinner.classList.remove('d-none');
  btn.disabled = true;

  try {
    const resp = await fetch(defaultsUrl, { method: 'GET' });
    if (resp.status === 204) {
      window.location.href = fallbackUrl;
      return;
    }
    await postJson(quickUrl, null);
    window.location.href = fallbackUrl;
  } catch (_err) {
    label.classList.remove('d-none');
    spinner.classList.add('d-none');
    btn.disabled = false;
  }
});

// ── Batch operations ───────────────────────────────────────────────────────

function _checkedUrls() {
  return Array.from(document.querySelectorAll('.batch-site-cb:checked'))
    .map(cb => cb.value);
}

function _syncSubmitBtn() {
  const btn = document.getElementById('batch-submit-btn');
  if (!btn) return;
  btn.disabled = _checkedUrls().length === 0;
}

// Select-all checkbox
document.addEventListener('change', (e) => {
  if (!e.target.matches('[data-action="batch-select-all"]')) return;
  const checked = e.target.checked;
  document.querySelectorAll('.batch-site-cb').forEach(cb => { cb.checked = checked; });
  _syncSubmitBtn();
});

// Individual checkboxes
document.addEventListener('change', (e) => {
  if (!e.target.matches('[data-action="batch-select-site"]')) return;
  _syncSubmitBtn();
  // Uncheck select-all if any individual box is unchecked
  const all = document.getElementById('batch-select-all');
  if (all) {
    const cbs = document.querySelectorAll('.batch-site-cb');
    all.checked = cbs.length > 0 && Array.from(cbs).every(cb => cb.checked);
  }
});

// Submit batch job
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action="batch-submit"]');
  if (!btn) return;

  const urls = _checkedUrls();
  if (urls.length === 0) return;

  const operation = (document.getElementById('batch-op-select') || {}).value || 'keep_alive';
  const queueUrl  = btn.dataset.queueUrl;
  const statusUrl = btn.dataset.statusUrl;
  const feedback  = document.getElementById('batch-feedback');

  btn.disabled = true;
  if (feedback) feedback.textContent = '提交中…';

  try {
    const data = await postJson(queueUrl, { site_urls: urls, operation });
    if (feedback) feedback.textContent = `已排入 ${data.queued} 个任务`;
    _pollBatchStatus(statusUrl);
  } catch (err) {
    if (feedback) feedback.textContent = `提交失败：${err.message}`;
    btn.disabled = false;
  }
});

// Poll /sites/batch-status every 5s until all rows are done/failed
let _pollTimer = null;

function _pollBatchStatus(statusUrl) {
  if (_pollTimer) clearTimeout(_pollTimer);

  async function _tick() {
    try {
      const data = await fetchJson(statusUrl + '?limit=100');
      _applyStatusRows(data.rows || []);
      const pending = (data.rows || []).some(r => r.status === 'pending' || r.status === 'processing');
      if (pending) _pollTimer = setTimeout(_tick, 5000);
    } catch (_err) {
      // Silently stop polling on error
    }
  }

  _tick();
}

// ── Autopilot toggle ───────────────────────────────────────────────────────

function _intervalForRow(siteUrl) {
  const select = document.querySelector(
    `[data-autopilot-interval][data-site-url="${CSS.escape(siteUrl)}"]`
  );
  if (!select) return 86400;
  if (select.value === 'custom') {
    const custom = document.querySelector(
      `[data-autopilot-custom-seconds][data-site-url="${CSS.escape(siteUrl)}"]`
    );
    return custom ? parseInt(custom.value, 10) || 86400 : 86400;
  }
  return parseInt(select.value, 10) || 86400;
}

// Show/hide custom seconds input when interval select changes
document.addEventListener('change', (e) => {
  if (!e.target.matches('[data-autopilot-interval]')) return;
  const siteUrl = e.target.dataset.siteUrl;
  const custom = document.querySelector(
    `[data-autopilot-custom-seconds][data-site-url="${CSS.escape(siteUrl)}"]`
  );
  if (!custom) return;
  if (e.target.value === 'custom') {
    custom.classList.remove('d-none');
  } else {
    custom.classList.add('d-none');
  }
});

document.addEventListener('change', async (e) => {
  const cb = e.target.closest('[data-action="toggle-autopilot"]');
  if (!cb) return;

  const siteUrl = cb.dataset.siteUrl;
  const autopilotUrl = cb.dataset.autopilotUrl;
  const enabled = cb.checked;
  const statusCell = cb.closest('tr')?.querySelector('.autopilot-row-status');

  cb.disabled = true;
  if (statusCell) statusCell.textContent = '保存中…';

  try {
    const intervalSeconds = enabled ? _intervalForRow(siteUrl) : 86400;
    await postJson(autopilotUrl, { site_url: siteUrl, enabled, interval_seconds: intervalSeconds });
    if (statusCell) {
      statusCell.textContent = enabled ? '已启用 ✓' : '已禁用';
      statusCell.className = 'autopilot-row-status small ' + (enabled ? 'text-success' : 'text-muted');
    }
  } catch (err) {
    cb.checked = !enabled;
    if (statusCell) {
      statusCell.textContent = `失败：${err.message}`;
      statusCell.className = 'autopilot-row-status small text-danger';
    }
  } finally {
    cb.disabled = false;
  }
});

// ── Dismiss autopilot alert (health dashboard banner) ─────────────────────

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action="dismiss-autopilot-alert"]');
  if (!btn) return;

  const siteUrl = btn.dataset.siteUrl;
  const dismissUrl = btn.dataset.dismissUrl;
  btn.disabled = true;

  try {
    await postJson(dismissUrl, { site_url: siteUrl });
    const li = btn.closest('li');
    if (li) li.remove();
    const banner = document.getElementById('autopilot-alert-banner');
    if (banner && !banner.querySelector('li')) banner.remove();
  } catch (_err) {
    btn.disabled = false;
  }
});

function _applyStatusRows(rows) {
  const urlStatusMap = {};
  for (const row of rows) {
    // Keep the most recent status per site_url (rows sorted desc)
    if (!(row.site_url in urlStatusMap)) urlStatusMap[row.site_url] = row.status;
  }

  document.querySelectorAll('#batch-sites-tbody tr[data-site-url]').forEach(tr => {
    const url = tr.dataset.siteUrl;
    const cell = tr.querySelector('.batch-row-status');
    if (!cell || !(url in urlStatusMap)) return;
    const status = urlStatusMap[url];
    const labels = { pending: '待处理', processing: '处理中', done: '完成 ✓', failed: '失败 ✗' };
    cell.textContent = labels[status] || status;
    cell.className = 'batch-row-status small ' + (
      status === 'done'       ? 'text-success' :
      status === 'failed'     ? 'text-danger'  :
      status === 'processing' ? 'text-warning' : 'text-muted'
    );
  });
}
