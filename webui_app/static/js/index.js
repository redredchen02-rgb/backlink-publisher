// Index page entry — native ES module (Plan 2026-06-01-007 Unit 6).
//
// Replaces the bare top-level index_main.js. All cross-script window globals are
// internalized: __rewireBulkSelect (module var), window.urlDerive (imported),
// window.fetchJson (via lib/api). The 7 config-form fns live in lib/profiles.js.
// Inline on* handlers became data-action; the inline urlDerive-consumer and the
// mode_toggle/url_derive auto-inits are driven from here.

import { on, delegate, qsa } from './lib/dom.js';
import { createConfigForm } from './lib/profiles.js';
import { bindPasteInput } from './url_derive.js';
import { initModeToggle } from './mode_toggle.js';
import { fetchJson } from './lib/api.js';
import { renderEmpty, renderError } from './ui/states.js';
import { classifyError } from './ui/errors.js';

const BOOT = window.__indexBootstrap || {};
const PLATFORM_SLUGS = BOOT.platform_slugs || [];
// has_channels: whether any publish channel is bound (server-injected from
// bound_platforms). false => true zero-config; true => config exists.
const HAS_CHANNELS = BOOT.has_channels === true;

function goToSettings() {
  window.location.href = '/settings';
}
const cf = createConfigForm({ plansData: BOOT.plans_list || [], profiles: BOOT.profiles || [] });

function loadHistory(id) {
  window.location.href = '/ce:history?id=' + id;
}

// ── data-action wiring ───────────────────────────────────────────
const CLICK_ACTIONS = {
  'load-history': (e, el) => loadHistory(el.dataset.id),
  'save-profile': () => cf.saveProfilePrompt(),
  'toggle-editor': (e, el) => cf.toggleEditor(el.dataset.idx),
  'save-edit': (e, el) => cf.saveEdit(el.dataset.idx),
  'cancel-edit': (e, el) => cf.cancelEdit(el.dataset.idx, el.dataset.original),
  'regen-body': (e, el) => cf.regenBody(el.dataset.idx, el.dataset.domain, el.dataset.language, JSON.parse(el.dataset.anchors), el.dataset.topic || null),
  'append-tag': (e, el) => {
    const tagsEl = document.getElementsByName('custom_tags')[0];
    if (tagsEl) tagsEl.value += el.dataset.tag + ',';
  },
  // Pro Mode activation nudge dismiss (plan 2026-06-05-003 U4). Hide + persist
  // a state-keyed flag so the nudge stays gone for this state but reappears if
  // the Pro state regresses (e.g. unconfigured → gen-off).
  'pro-nudge-dismiss': () => {
    const nudge = document.getElementById('pro-activation-nudge');
    if (!nudge) return;
    nudge.style.display = 'none';
    try { localStorage.setItem('proNudgeDismissed', nudge.dataset.nudgeState || '1'); } catch (_) {}
  },
};
const CHANGE_ACTIONS = {
  'load-profile': (e, el) => cf.loadProfile(el.value),
  'load-batch-profile': (e, el) => cf.loadBatchProfile(el.value),
};
const KEYUP_ACTIONS = {
  'mark-dirty': (e, el) => cf.markDirty(el.dataset.idx),
};

function _initActions() {
  delegate(document, 'click', '[data-action]', (e, el) => {
    const h = CLICK_ACTIONS[el.dataset.action];
    if (h) { e.preventDefault(); h(e, el); }
  });
  delegate(document, 'change', '[data-action]', (e, el) => {
    const h = CHANGE_ACTIONS[el.dataset.action];
    if (h) h(e, el);
  });
  delegate(document, 'keyup', '[data-action]', (e, el) => {
    const h = KEYUP_ACTIONS[el.dataset.action];
    if (h) h(e, el);
  });
  // `return confirm(...)` guards → preventDefault on cancel (forms + buttons).
  delegate(document, 'submit', 'form[data-confirm]', (e, form) => {
    if (!confirm(form.dataset.confirm)) e.preventDefault();
  });
  delegate(document, 'click', 'button[data-confirm]', (e, btn) => {
    if (!confirm(btn.dataset.confirm)) e.preventDefault();
  });
}

// ── Loading overlay ──────────────────────────────────────────────
function _initLoadingOverlay() {
  const MSGS = {
    '/ce:plan': { text: '分析网址中…', sub: '正在抓取页面元数据' },
    '/ce:generate': { text: 'AI 生成文章中…', sub: '调用 AI 生成外链文章，约需 30–60 秒' },
    '/ce:validate': { text: '验证内容中…', sub: '检查外链格式与内容合规性' },
    '/ce:publish': { text: '发布中…', sub: '正在发布到目标平台，请勿关闭页面' },
    '/ce:publish-real': { text: '正式发布中…', sub: '正在写入平台，请勿关闭页面' },
    '/ce:batch': { text: '批量发布中…', sub: '正在逐篇生成并发布，每篇约 30–60 秒，请勿关闭页面' },
    '/checkpoint/resume': { text: '恢复发布中…', sub: '正在处理未完成的发布任务，可能需要数分钟，请勿关闭页面' },
  };
  on(document, 'submit', (e) => {
    const form = e.target;
    const action = ((form.getAttribute && form.getAttribute('action')) || '').split('?')[0];
    if (['/ce:clear', '/ce:history/delete', '/ce:history/update-status'].includes(action)) return;
    const msg = MSGS[action] || { text: '处理中…', sub: '请稍候' };
    const t = document.getElementById('_loadingText');
    const s = document.getElementById('_loadingSubtext');
    const overlay = document.getElementById('_loadingOverlay');
    if (t) t.textContent = msg.text;
    if (s) s.textContent = msg.sub;
    if (overlay) overlay.style.display = 'flex';
    form.querySelectorAll('[type="submit"]').forEach((btn) => { btn.disabled = true; });
  });
}

// ── History filter (status × platform) — calls rewireBulkSelect ──
let rewireBulkSelect = null;

function _initHistoryFilter() {
  const cardBody = document.getElementById('historyCardBody');
  if (!cardBody) return;
  const items = cardBody.querySelectorAll('.history-item[data-status]');
  if (!items.length) return;
  const chips = cardBody.querySelectorAll('.filter-chip');
  const emptyFiltered = document.getElementById('historyEmptyFiltered');
  let currentStatus = 'all';
  let currentPlatform = 'all';

  // Filtered-empty cause #2 (has config, current filter has no results): unified
  // renderEmpty with「当前条件无结果」+ a clear-filter action — NEVER the 去配置 CTA.
  // renderEmpty calls replaceChildren (idempotent + cheap), so we render on every
  // empty filter instead of guarding with a once-flag that could keep a stale view.
  function showFilteredEmpty() {
    if (!emptyFiltered) return;
    emptyFiltered.style.display = '';
    renderEmpty(emptyFiltered, {
      icon: 'bi-funnel',
      title: '当前条件无结果',
      message: '没有符合当前筛选的记录，试试切换或清除筛选条件。',
      actionLabel: '清除筛选',
      onAction: () => {
        currentStatus = 'all';
        currentPlatform = 'all';
        chips.forEach((c) => c.classList.toggle('active', c.dataset.filterValue === 'all'));
        applyFilter();
        if (typeof rewireBulkSelect === 'function') rewireBulkSelect();
      },
    });
  }

  function applyFilter() {
    let visible = 0;
    items.forEach((item) => {
      const matchStatus = (currentStatus === 'all') || (item.dataset.status === currentStatus);
      const matchPlatform = (currentPlatform === 'all') || (item.dataset.platform === currentPlatform);
      if (matchStatus && matchPlatform) { item.style.display = ''; visible++; } else { item.style.display = 'none'; }
    });
    if (visible === 0) showFilteredEmpty();
    else if (emptyFiltered) emptyFiltered.style.display = 'none';
  }

  function initCounts() {
    const counts = {
      status: { all: 0, drafted: 0, published: 0, failed: 0, other: 0 },
      platform: Object.assign({ all: 0 }, Object.fromEntries(PLATFORM_SLUGS.map((s) => [s, 0])), { other: 0 }),
    };
    items.forEach((item) => {
      counts.status.all++;
      counts.platform.all++;
      const st = item.dataset.status;
      const pf = item.dataset.platform;
      if (counts.status[st] !== undefined) counts.status[st]++;
      if (counts.platform[pf] !== undefined) counts.platform[pf]++;
    });
    let unverifiedCount = 0;
    items.forEach((item) => { if (item.dataset.status === 'unverified') unverifiedCount++; });
    counts.status.unverified = unverifiedCount;
    chips.forEach((chip) => {
      const group = chip.dataset.filterGroup;
      const value = chip.dataset.filterValue;
      const span = chip.querySelector('.chip-count');
      if (span && counts[group] && counts[group][value] !== undefined) span.textContent = counts[group][value];
    });
  }

  chips.forEach((chip) => {
    on(chip, 'click', () => {
      const group = chip.dataset.filterGroup;
      const value = chip.dataset.filterValue;
      if (group === 'status') currentStatus = value;
      else if (group === 'platform') currentPlatform = value;
      cardBody.querySelectorAll('.filter-chip[data-filter-group="' + group + '"]').forEach((sib) => sib.classList.remove('active'));
      chip.classList.add('active');
      applyFilter();
      if (typeof rewireBulkSelect === 'function') rewireBulkSelect();
    });
  });

  initCounts();
  applyFilter();
}

// ── Bulk-select (defines rewireBulkSelect) + tooltips + img fallback ──
function _initBulkSelect() {
  function wireSection(rootId, selectAllId, checkboxClass, countLabelId, btnClass) {
    const root = document.getElementById(rootId);
    if (!root) return null;
    const selectAll = document.getElementById(selectAllId);
    const countLabel = document.getElementById(countLabelId);
    if (!selectAll) return null;
    const buttons = document.querySelectorAll('.' + btnClass);

    function visibleCheckboxes() {
      return Array.prototype.filter.call(root.querySelectorAll('.' + checkboxClass), (cb) => {
        const host = cb.closest('.history-item');
        return host && host.style.display !== 'none';
      });
    }
    function refresh() {
      const visible = visibleCheckboxes();
      const checked = visible.filter((cb) => cb.checked);
      if (countLabel) countLabel.textContent = '(' + checked.length + '/' + visible.length + ')';
      buttons.forEach((btn) => { btn.disabled = checked.length === 0; });
      if (visible.length === 0) { selectAll.indeterminate = false; selectAll.checked = false; }
      else if (checked.length === visible.length) { selectAll.indeterminate = false; selectAll.checked = true; }
      else if (checked.length === 0) { selectAll.indeterminate = false; selectAll.checked = false; }
      else { selectAll.indeterminate = true; }
    }
    on(selectAll, 'change', () => {
      const target = selectAll.checked;
      visibleCheckboxes().forEach((cb) => { cb.checked = target; });
      refresh();
    });
    on(document, 'change', (e) => {
      if (e.target.classList && e.target.classList.contains(checkboxClass)) refresh();
    });
    return refresh;
  }
  const refreshDraft = wireSection('draftCardBody', 'draftSelectAll', 'draft-bulk-select', 'draftSelectedCount', 'draft-bulk-btn');
  const refreshHistory = wireSection('historyCardBody', 'historySelectAll', 'history-bulk-select', 'historySelectedCount', 'history-bulk-btn');

  // Module-scoped (was window.__rewireBulkSelect) — history filter calls this.
  rewireBulkSelect = function () {
    if (refreshHistory) {
      const root = document.getElementById('historyCardBody');
      if (root) {
        root.querySelectorAll('.history-bulk-select').forEach((cb) => {
          const host = cb.closest('.history-item');
          if (host && host.style.display === 'none' && cb.checked) cb.checked = false;
        });
      }
      refreshHistory();
    }
    if (refreshDraft) refreshDraft();
  };
  if (refreshDraft) refreshDraft();
  if (refreshHistory) refreshHistory();

  // Bootstrap tooltips + broken-image fallback.
  if (window.bootstrap) {
    qsa('[data-bs-toggle="tooltip"]').forEach((el) => new window.bootstrap.Tooltip(el));
  }
  qsa('.content-preview img').forEach((img) => {
    img.onerror = function () {
      img.style.display = 'none';
      const warn = document.createElement('div');
      warn.className = 'alert alert-secondary py-1 px-2 my-2 d-inline-block';
      warn.style.fontSize = '12px';
      warn.innerHTML = "<i class='bi bi-image-alt me-1'></i>封面图片加载失败";
      img.parentNode.insertBefore(warn, img.nextSibling);
    };
  });
}

// ── url-derive paste binding (was the index inline <script>) ─────
function _initUrlDerive() {
  const pasteEl = document.getElementById('derive_source');
  if (!pasteEl) return;
  bindPasteInput(
    pasteEl,
    {
      main: document.querySelector('input[name="main_url"]'),
      category: document.querySelector('input[name="category_url"]'),
      work: document.querySelector('input[name="work_url"]'),
    },
    {
      main: document.getElementById('status-main'),
      category: document.getElementById('status-category'),
      work: document.getElementById('status-work'),
    },
  );
}

// ── Flash auto-dismiss (U5: R17) ────────────────────────────────
function _initFlashDismiss() {
  // Only auto-dismiss non-critical alerts; danger/warning must persist until manually closed.
  document.querySelectorAll('.alert-success.alert-dismissible, .alert-info.alert-dismissible').forEach((el) => {
    setTimeout(() => { if (el.isConnected) el.remove(); }, 4000);
  });
}

// ── Pro Mode activation nudge (U4) ───────────────────────────────
function _initProNudge() {
  const nudge = document.getElementById('pro-activation-nudge');
  if (!nudge) return;
  try {
    // Hide only if previously dismissed for the *same* state; a regressed
    // state writes a different key, so the nudge reappears.
    if (localStorage.getItem('proNudgeDismissed') === (nudge.dataset.nudgeState || '1')) {
      nudge.style.display = 'none';
    }
  } catch (_) { /* localStorage unavailable — show the nudge */ }
}

// ── Health summary bar (Plan 2026-06-09-001 U3) ──────────────────
function _initHealthBar() {
  const bar = document.getElementById('health-summary-bar');
  if (!bar) return;
  const DISMISS_KEY = 'healthBarDismissed';
  try { if (sessionStorage.getItem(DISMISS_KEY)) return; } catch (_) { /* ignore */ }

  const icon = document.getElementById('health-summary-icon');
  const text = document.getElementById('health-summary-text');

  fetchJson('/health').then((data) => {
    if (!data) return;
    const healthy = data.healthy;
    const reasons = data.degraded_reasons || [];
    // A brand-new install (or a channel just bound, nothing published yet) is
    // not the same situation as an actual failure — don't show the alarming
    // "degraded" treatment for it. /health's healthy/degraded_reasons contract
    // (and its 503 status, used by monitoring) is unchanged; this only affects
    // how the banner is presented (2026-07-06, U15 B2).
    const neverPublished = !healthy && reasons.length === 1 && reasons[0] === 'pipeline:never_run';
    bar.classList.remove('d-none');
    bar.classList.toggle('healthy', healthy);
    bar.classList.toggle('pending', neverPublished);
    bar.classList.toggle('degraded', !healthy && !neverPublished);
    if (icon) icon.textContent = healthy ? '✅' : (neverPublished ? 'ℹ️' : '⚠️');
    if (text) {
      text.textContent = healthy
        ? `系统正常 · 已绑定 ${Object.keys(data.channels || {}).length} 个渠道`
        : neverPublished
          ? '尚未发布任何内容 · 完成渠道设置后即可开始发布'
          : `系统降级 · ${reasons.join(', ')}`;
    }
  }).catch(() => { /* fail-open: no bar shown on error */ });

  // Dismiss handler
  delegate(bar, '[data-action="health-bar-dismiss"]', 'click', () => {
    bar.classList.add('d-none');
    try { sessionStorage.setItem(DISMISS_KEY, '1'); } catch (_) { /* ignore */ }
  });
}

// ── Empty-state onboarding (U2: R2) ──────────────────────────────
// Unifies the three "empty" causes on the zero-history container:
//   1. true zero-config (no bound channel)   → renderEmpty + 去配置 CTA
//   2. has config but this view has no data   → renderEmpty, NO config CTA
//   3. the state itself could not be derived  → renderError (not an empty state)
// Cause #2 for filters is handled inline in _initHistoryFilter (clear-filter).
function _initEmptyState() {
  const container = document.getElementById('indexEmptyState');
  if (!container) return;  // history is non-empty; nothing to render
  try {
    if (!HAS_CHANNELS) {
      renderEmpty(container, {
        icon: 'bi-rocket-takeoff',
        title: '先去配置一个发布渠道',
        message: '还没有绑定任何渠道，去设置页绑定第一个渠道即可开始发布。',
        actionLabel: '去配置',
        onAction: goToSettings,
      });
    } else {
      renderEmpty(container, {
        icon: 'bi-inbox',
        title: '当前条件无结果',
        message: '还没有发布记录，去「新建任务」发布第一条外链。',
      });
    }
  } catch (err) {
    // Region load failure → inline renderError via the shared taxonomy (toast is
    // for transient action feedback only). Same title/message source everywhere.
    const c = classifyError(err);
    renderError(container, {
      title: c.title,
      message: c.message,
      onRetry: () => window.location.reload(),
    });
  }
}

// ── boot ─────────────────────────────────────────────────────────
function _boot() {
  _initActions();
  _initLoadingOverlay();
  _initHistoryFilter();
  _initBulkSelect();   // defines rewireBulkSelect — before filter clicks fire
  _initUrlDerive();
  initModeToggle();
  _initFlashDismiss();
  _initProNudge();
  _initHealthBar();
  _initEmptyState();
}

if (document.readyState === 'loading') on(document, 'DOMContentLoaded', _boot); else _boot();
