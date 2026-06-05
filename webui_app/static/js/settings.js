// Settings page entry — native ES module (Plan 2026-06-01-007 Unit 3).
//
// Replaces the bare top-level settings_main.js: every former window-leaked
// function is now module-scoped and wired via data-action event delegation
// (no inline on*). Untrusted text goes through esc()/textContent — never raw
// innerHTML interpolation. The CSRF token is read fresh per call (readCsrf).
//
// NOTE: the 7 profile/editor functions that settings_main.js also defined
// (toggleEditor/markDirty/saveEdit/cancelEdit/loadProfile/loadBatchProfile/
// saveProfilePrompt) were DEAD here — never called by any settings template
// (they belong to the index config-form). They are dropped, not ported; the
// live index copies move to lib/profiles.js in Unit 6.

import { fetchJson, readCsrf } from './lib/api.js';
import { esc, on, delegate, qs } from './lib/dom.js';

// ── Blog ID 行管理 (blogger) ─────────────────────────────────────
function addRow() {
  const container = document.getElementById('blogIdRows');
  if (!container) return;
  const row = document.createElement('div');
  row.className = 'blog-id-row';
  // DOM API, no untrusted interpolation; the remove button carries data-action.
  const domain = document.createElement('input');
  domain.type = 'text';
  domain.className = 'form-control form-control-sm';
  domain.name = 'domain[]';
  domain.placeholder = 'https://your-site.com';
  const blogId = document.createElement('input');
  blogId.type = 'text';
  blogId.className = 'form-control form-control-sm token-box';
  blogId.name = 'blog_id[]';
  blogId.placeholder = '1234567890123456789';
  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'btn btn-outline-danger btn-sm';
  del.dataset.action = 'remove-row';
  del.innerHTML = '<i class="bi bi-trash"></i>';
  row.append(domain, blogId, del);
  container.appendChild(row);
}

function removeRow(btn) {
  const row = btn.closest('.blog-id-row');
  if (row) row.remove();
}

// ── 复制 Redirect URI (blogger) ──────────────────────────────────
function copyUri() {
  const el = document.getElementById('callbackUriDisplay');
  if (!el) return;
  navigator.clipboard.writeText(el.value).then(() => {
    const btn = document.getElementById('copyBtn');
    if (!btn) return;
    btn.innerHTML = '<i class="bi bi-check2 me-1"></i>已复制';
    btn.classList.replace('btn-warning', 'btn-success');
    setTimeout(() => {
      btn.innerHTML = '<i class="bi bi-clipboard me-1"></i>复制';
      btn.classList.replace('btn-success', 'btn-warning');
    }, 2000);
  });
}

// ── Show/hide secret fields ──────────────────────────────────────
function _toggleField(inputId, iconId) {
  const input = document.getElementById(inputId);
  const icon = document.getElementById(iconId);
  if (!input || !icon) return;
  if (input.type === 'password') {
    input.type = 'text';
    icon.className = 'bi bi-eye-slash';
  } else {
    input.type = 'password';
    icon.className = 'bi bi-eye';
  }
}
const toggleSecret = () => _toggleField('clientSecretInput', 'secretEye');
const toggleLlmSecret = () => _toggleField('llmApiKeyInput', 'llmSecretEye');
const toggleToken = () => _toggleField('mediumTokenInput', 'eyeIcon');

// ── LLM helpers ──────────────────────────────────────────────────
function resetLlmPrompt() {
  if (confirm('确定要恢复默认系统提示词吗？')) {
    const el = document.getElementById('llmPromptInput');
    if (el) el.value = '';
  }
}

function clearLlmSettings() {
  if (confirm('确定要清除所有 LLM 配置吗？这将还原为系统默认生成模式。')) {
    const marker = document.getElementById('llmFormAction');
    if (marker) marker.value = 'clear';
    const form = document.querySelector('form[action="/settings/save-llm-config"]');
    if (form) form.submit();
  }
}

const _LLM_PRESETS = {
  openai: { url: 'https://api.openai.com/v1', model: 'gpt-4o' },
  deepseek: { url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  openrouter: { url: 'https://openrouter.ai/api/v1', model: 'openai/gpt-4o-mini' },
  groq: { url: 'https://api.groq.com/openai/v1', model: 'llama3-70b-8192' },
  local: { url: 'http://localhost:11434/v1', model: 'llama3' },
};
function applyLlmPreset(provider) {
  const preset = _LLM_PRESETS[provider];
  if (!preset) return;
  const endpointEl = document.getElementById('llmEndpointInput');
  const modelEl = document.getElementById('llmModelInput');
  if (endpointEl) endpointEl.value = preset.url;
  if (modelEl) modelEl.value = preset.model;
  const result = document.getElementById('llmTestResult');
  if (result) result.replaceChildren();
  const selBtn = document.getElementById('modelSelectBtn');
  if (selBtn) selBtn.classList.add('d-none');
}

function selectLlmModel(model) {
  const modelEl = document.getElementById('llmModelInput');
  if (modelEl) modelEl.value = model;
  const form = document.querySelector('form[action="/settings/save-llm-config"]');
  if (form) form.submit();
}

// helper: render a status line (icon + escaped message) into a result element.
function _statusLine(el, kind, iconClass, message) {
  if (!el) return;
  const span = document.createElement('span');
  span.className = kind;
  const i = document.createElement('i');
  i.className = iconClass;
  span.append(i, ' ', String(message == null ? '' : message));
  el.replaceChildren(span);
}

async function testLlmConnection(btn) {
  const resEl = document.getElementById('llmTestResult');
  const endpoint = qs('input[name="endpoint"]');
  const apiKey = qs('input[name="api_key"]');
  const model = qs('input[name="model"]');
  _statusLine(resEl, 'text-muted', 'bi bi-hourglass-split', '测试中...');
  if (btn) btn.disabled = true;
  try {
    const formData = new FormData();
    formData.append('endpoint', endpoint ? endpoint.value : '');
    formData.append('api_key', apiKey ? apiKey.value : '');
    formData.append('model', model ? model.value : '');
    formData.append('csrf_token', readCsrf());
    const data = await fetchJson('/settings/test-llm-connection', {
      method: 'POST', body: formData, headers: { 'X-CSRFToken': readCsrf() },
    });
    if (data.status === 'ok') {
      _statusLine(resEl, 'text-success', 'bi bi-check-circle', data.message);
      if (data.models && data.models.length > 0) {
        const list = document.getElementById('modelDropdownList');
        const selBtn = document.getElementById('modelSelectBtn');
        if (list) {
          list.replaceChildren();
          // model ids are UNTRUSTED (verbatim from the provider's /models) —
          // carry via dataset + textContent, never interpolated innerHTML.
          data.models.slice().sort().forEach((m) => {
            const li = document.createElement('li');
            const a = document.createElement('a');
            a.className = 'dropdown-item';
            a.href = '#';
            a.style.fontSize = '13px';
            a.dataset.action = 'llm-select-model';
            a.dataset.model = m;
            a.textContent = m;
            li.appendChild(a);
            list.appendChild(li);
          });
        }
        if (selBtn) selBtn.classList.remove('d-none');
      }
    } else {
      _statusLine(resEl, 'text-danger', 'bi bi-x-circle', data.message);
    }
  } catch (e) {
    _statusLine(resEl, 'text-danger', 'bi bi-x-circle', '网络错误: ' + (e && e.message ? e.message : e));
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Diagnostics: preview generation ──────────────────────────────
async function previewGeneration() {
  const resEl = document.getElementById('previewResult');
  const title = document.getElementById('testTitle');
  if (resEl) resEl.textContent = '生成中...';
  try {
    const formData = new FormData();
    formData.append('test_title', title ? title.value : '');
    formData.append('csrf_token', readCsrf());
    const data = await fetchJson('/settings/test-llm-generation', {
      method: 'POST', body: formData, headers: { 'X-CSRFToken': readCsrf() },
    });
    if (resEl) resEl.textContent = data.status === 'ok' ? data.result : ('错误: ' + data.message);
  } catch (e) {
    if (resEl) resEl.textContent = '请求失败: ' + (e && e.message ? e.message : e);
  }
}

// ── AI Banner image-gen test ─────────────────────────────────────
function _alertBox(el, kind, iconClass, message, extraNode) {
  if (!el) return;
  const div = document.createElement('div');
  div.className = 'alert ' + kind + ' mb-0';
  div.style.fontSize = '13px';
  const i = document.createElement('i');
  i.className = iconClass + ' me-1';
  div.append(i, String(message == null ? '' : message));
  if (extraNode) div.append(extraNode);
  el.replaceChildren(div);
}

async function testImageGenConnection(btn) {
  const result = document.getElementById('imageGenTestResult');
  if (!btn || !result) return;
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Testing…';
  result.style.display = 'block';
  result.replaceChildren();
  try {
    const resp = await fetch('/settings/test-image-gen', {
      method: 'POST', headers: { 'X-CSRFToken': readCsrf() },
    });
    const data = await resp.json();
    if (data.ok) {
      let line;
      if (data.frw_credits_remaining !== undefined) {
        line = `FRW endpoint reachable; credits remaining: ${data.frw_credits_remaining}`;
      } else if (data.model_count !== undefined) {
        line = `endpoint reachable; ${data.model_count} models advertised`;
      } else if (data.note) {
        line = esc(data.note);
      } else {
        line = 'endpoint reachable';
      }
      let extra = null;
      if (data.configured_model) {
        const small = document.createElement('small');
        small.innerHTML = '<br>Configured model: <code>' + esc(data.configured_model) + '</code>';
        extra = small;
      }
      _alertBox(result, 'alert-success', 'bi bi-check-circle', line, extra);
    } else {
      _alertBox(result, 'alert-danger', 'bi bi-x-circle', data.error || 'unknown error');
    }
  } catch (e) {
    _alertBox(result, 'alert-danger', 'bi bi-x-circle', 'fetch failed: ' + (e && e.message ? e.message : e));
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-cloud-check me-1"></i>Test Connection';
  }
}

// ── Banner 测试图：localStorage 快取 ────────────────────────────
const _LS_BANNER_KEY = 'bp:banner_last_image';

function _renderBannerResult(result, data, { cached = false } = {}) {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'border:1px solid var(--border,#dee2e6);border-radius:8px;overflow:hidden;';
  if (cached) {
    const bar = document.createElement('div');
    bar.style.cssText = 'padding:5px 12px;font-size:11px;color:#6b7280;background:#fffbeb;border-bottom:1px solid var(--border,#dee2e6);display:flex;justify-content:space-between;align-items:center;';
    const ts = new Date(data.generated_at).toLocaleString();
    const lbl = document.createElement('span');
    lbl.textContent = `上次生成于 ${ts}`;
    const clr = document.createElement('button');
    clr.type = 'button';
    clr.className = 'btn btn-link btn-sm p-0';
    clr.style.cssText = 'font-size:11px;color:#9ca3af;';
    clr.dataset.action = 'clear-banner-cache';
    clr.textContent = '清除';
    bar.append(lbl, clr);
    wrap.append(bar);
  }
  const img = document.createElement('img');
  img.src = data.data_url;
  img.alt = 'Sample banner';
  img.style.cssText = 'width:100%;max-height:280px;object-fit:contain;display:block;background:#f8f9fa;';
  const meta = document.createElement('div');
  meta.style.cssText = 'padding:8px 12px;font-size:12px;color:#6b7280;background:#f8f9fa;border-top:1px solid var(--border,#dee2e6);';
  meta.textContent = `${data.mime} · ${data.size_kb} KB · prompt: ${data.prompt}`;
  if (data.source_url) {
    const a = document.createElement('a');
    a.href = data.source_url;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = ' · 原始链接';
    meta.append(a);
  }
  wrap.append(img, meta);
  result.replaceChildren(wrap);
  result.style.display = 'block';
}

function _saveBannerToCache(data) {
  try {
    localStorage.setItem(_LS_BANNER_KEY, JSON.stringify({
      data_url: data.data_url, mime: data.mime, size_kb: data.size_kb,
      prompt: data.prompt, source_url: data.source_url || null,
      generated_at: Date.now(),
    }));
  } catch (e) { /* QuotaExceededError — skip */ }
}

function _clearBannerCache() {
  try { localStorage.removeItem(_LS_BANNER_KEY); } catch (e) { /* ignore */ }
  const result = document.getElementById('imageGenSampleResult');
  if (result) { result.replaceChildren(); result.style.display = 'none'; }
}

function _restoreCachedBannerImage() {
  const result = document.getElementById('imageGenSampleResult');
  if (!result) return;
  let cached;
  try {
    const raw = localStorage.getItem(_LS_BANNER_KEY);
    if (!raw) return;
    cached = JSON.parse(raw);
  } catch (e) { return; }
  if (!cached || !cached.data_url) return;
  _renderBannerResult(result, cached, { cached: true });
}

async function generateSampleImage(btn) {
  const result = document.getElementById('imageGenSampleResult');
  const promptEl = document.getElementById('imageGenPromptInput');
  if (!btn || !result) return;
  const customPrompt = promptEl ? promptEl.value.trim() : '';
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>生成中…';
  result.style.display = 'block';
  result.replaceChildren();
  try {
    const resp = await fetch('/settings/generate-sample-image', {
      method: 'POST',
      headers: { 'X-CSRFToken': readCsrf(), 'Content-Type': 'application/json' },
      body: JSON.stringify(customPrompt ? { prompt: customPrompt } : {}),
    });
    const data = await resp.json();
    if (data.ok) {
      data.generated_at = Date.now();
      _renderBannerResult(result, data);
      _saveBannerToCache(data);
    } else {
      _alertBox(result, 'alert-danger', 'bi bi-x-circle', data.error || 'generation failed');
    }
  } catch (e) {
    _alertBox(result, 'alert-danger', 'bi bi-x-circle', 'fetch failed: ' + (e && e.message ? e.message : e));
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-image me-1"></i>生成测试图';
  }
}

// ── velog login (moved out of the _settings_channel_velog inline <script>) ──
// Reached from the velog dashboard card via a DOM CustomEvent (not the old
// `typeof runVelogLogin` global probe — that would silently fail under ESM).
function runVelogLogin() {
  fetchJson('/api/velog/login', { method: 'POST', headers: { 'X-CSRFToken': readCsrf() } })
    .then((d) => {
      if (d.ok) {
        alert('velog-login 已启动。\n请在弹出的 Chromium 窗口完成登录，完成后刷新本页。');
      } else {
        alert(d.message || ('启动失败：' + (d.error_code || '未知错误')));
      }
    })
    .catch(() => alert('网络错误，请手动在终端运行：\nvelog-login'));
}

// ── data-action wiring (replaces every inline on*) ───────────────
const _CLICK_ACTIONS = {
  'add-row': () => addRow(),
  'remove-row': (e, el) => removeRow(el),
  'copy-uri': () => copyUri(),
  'toggle-secret': () => toggleSecret(),
  'toggle-llm-secret': () => toggleLlmSecret(),
  'toggle-token': () => toggleToken(),
  'llm-preset': (e, el) => applyLlmPreset(el.dataset.preset),
  'llm-reset-prompt': () => resetLlmPrompt(),
  'llm-clear': () => clearLlmSettings(),
  'llm-test': (e, el) => testLlmConnection(el),
  'llm-select-model': (e, el) => selectLlmModel(el.dataset.model),
  'preview-generation': () => previewGeneration(),
  'test-image-gen': (e, el) => testImageGenConnection(el),
  'generate-sample-image': (e, el) => generateSampleImage(el),
  'clear-banner-cache': () => _clearBannerCache(),
  'velog-login': () => runVelogLogin(),
  'submit-revoke': () => { const f = document.getElementById('revokeForm'); if (f) f.submit(); },
  'copy-localhost': (e, el) => {
    navigator.clipboard.writeText('http://localhost').then(() => {
      el.textContent = '✓';
      setTimeout(() => { el.innerHTML = '<i class="bi bi-clipboard"></i>'; }, 1500);
    });
  },
};

function _initActions() {
  // Click delegation: a single document listener handles current + future nodes
  // (e.g. dynamically-added blog-id rows) and receives synthetic clicks.
  delegate(document, 'click', '[data-action]', (e, el) => {
    const handler = _CLICK_ACTIONS[el.dataset.action];
    if (handler) { e.preventDefault(); handler(e, el); }
  });

  // `return confirm(...)` guards → preventDefault when the user cancels.
  // Applies to forms (submit) and plain buttons (click) carrying data-confirm.
  delegate(document, 'submit', 'form[data-confirm]', (e, form) => {
    if (!confirm(form.dataset.confirm)) e.preventDefault();
  });
  delegate(document, 'click', 'button[data-confirm]', (e, btn) => {
    if (!confirm(btn.dataset.confirm)) e.preventDefault();
  });

  // LLM temperature slider live value (was oninput).
  const temp = document.getElementById('llmTemperature') || qs('[data-action="temp-slider"]');
  if (temp) {
    on(temp, 'input', () => {
      const out = document.getElementById('tempValue');
      if (out) out.innerText = temp.value;
    });
  }

  // velog dashboard-card bridge: channel-binding.js dispatches this event
  // instead of probing a window global.
  on(document, 'velog:login', () => runVelogLogin());
}

// ── Settings sidebar pane switch (U4, replaces _initStickyTabBar) ─
const HASH_TO_PANE = {
  '#channel-medium': 'channels',
  '#channel-blogger': 'channels',
  '#channel-velog': 'channels',
  '#channel-telegraph': 'channels',
  '#channel-ghpages': 'channels',
  '#channel-devto': 'channels',
  '#channel-notion': 'channels',
  '#section-channels': 'channels',
  '#section-global': 'global',
  '#section-llm': 'llm',
  // Pro Mode CTAs (nav pill / index nudge) deep-link to the real section id
  // so browser-native scroll works even without JS (plan 2026-06-05-003 U6).
  '#pane-llm': 'llm',
};

function _hashToPaneKey(hash) {
  return HASH_TO_PANE[hash] || null;
}

function showPane(key) {
  document.querySelectorAll('.settings-pane').forEach((el) => el.classList.remove('active'));
  const target = document.getElementById('pane-' + key);
  if (target) {
    target.classList.add('active');
  } else {
    // Stale sessionStorage key — fall back to dashboard to avoid blank page.
    const fallback = document.getElementById('pane-dashboard');
    if (fallback) fallback.classList.add('active');
  }
  document.querySelectorAll('[data-pane]').forEach((el) => {
    el.classList.toggle('active', el.dataset.pane === key);
  });
}

function _initActivePane() {
  // An explicit deep-link hash (e.g. /settings#pane-llm from a Pro CTA) wins
  // over the last-visited pane in sessionStorage, then scrolls the pane into
  // view so the nudge→action loop lands on the Pro pane (plan 2026-06-05-003 U6).
  const hashKey = _hashToPaneKey(window.location.hash);
  let key = hashKey;
  if (!key) {
    try { key = sessionStorage.getItem('settings:activePane'); } catch (e) { /* ignore */ }
  }
  if (!key) key = 'dashboard';
  showPane(key);
  if (hashKey) {
    const el = document.getElementById('pane-' + hashKey);
    if (el) el.scrollIntoView();
  }
}

function _initSidebarNav() {
  delegate(document, 'click', '[data-action="sidebar-nav"]', (e, el) => {
    const key = el.dataset.pane;
    if (!key) return;
    try { sessionStorage.setItem('settings:activePane', key); } catch (err) { /* ignore */ }
    showPane(key);
  });
}

function _initLoadingOverlay() {
  const MSGS = {
    '/ce:plan': { text: '分析网址中…', sub: '正在抓取页面元数据' },
    '/ce:generate': { text: 'AI 生成文章中…', sub: '调用 AI 生成外链文章，约需 30–60 秒' },
    '/ce:validate': { text: '验证内容中…', sub: '检查外链格式与内容合规性' },
    '/ce:publish': { text: '发布中…', sub: '正在发布到目标平台，请勿关闭页面' },
    '/ce:publish-real': { text: '正式发布中…', sub: '正在写入平台，请勿关闭页面' },
    '/ce:batch': { text: '批量发布中…', sub: '正在逐篇生成并发布，每篇约 30–60 秒，请勿关闭页面' },
    '/settings/medium/launch-browser-login': { text: '正在打开浏览器…', sub: '请在弹出窗口中完成登录（含可能的 email 验证码 / 2FA），完成后页面自动跳转' },
    '/settings/medium/probe-browser-login': { text: '探测 Medium 登录状态…', sub: '约需 5–15 秒' },
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

function _openCollapseForHash() {
  const id = window.location.hash.slice(1);
  if (!id) return;
  const target = document.getElementById(id);
  if (!target) return;
  const panel = target.closest('.collapse');
  if (panel && !panel.classList.contains('show') && window.bootstrap) {
    window.bootstrap.Collapse.getOrCreateInstance(panel).show();
    on(panel, 'shown.bs.collapse', () => target.scrollIntoView({ block: 'start' }), { once: true });
  }
}

function _initBindReopen() {
  let last = null;
  try { last = sessionStorage.getItem('bind:lastChannel'); } catch (e) { /* ignore */ }
  if (!last) return;
  const card = document.getElementById('channel-' + last);
  if (card && !card.classList.contains('show') && window.bootstrap) {
    try { window.bootstrap.Collapse.getOrCreateInstance(card).show(); } catch (e) { /* ignore */ }
    on(card, 'shown.bs.collapse', () => {
      const section = document.getElementById('bind-section-' + last);
      if (section) section.scrollIntoView({ block: 'center' });
    }, { once: true });
  }
  try { sessionStorage.removeItem('bind:lastChannel'); } catch (e) { /* ignore */ }
}

function _initOverviewPersistence() {
  const panel = document.getElementById('overview-panel');
  if (!panel || !window.bootstrap) return;
  let open = false;
  try { open = localStorage.getItem('settings:overviewOpen') === '1'; } catch (e) { /* ignore */ }
  if (open) { try { window.bootstrap.Collapse.getOrCreateInstance(panel).show(); } catch (e) { /* ignore */ } }
  on(panel, 'show.bs.collapse', () => { try { localStorage.setItem('settings:overviewOpen', '1'); } catch (e) { /* ignore */ } });
  on(panel, 'hide.bs.collapse', () => { try { localStorage.removeItem('settings:overviewOpen'); } catch (e) { /* ignore */ } });
}

// Plan 2026-06-05-007 — persist the extension-area collapse across re-renders.
// On cold start the server renders #ext-area with `show` + data-cold-start so
// the bind entry isn't buried; in that case we skip the saved-state replay once
// (don't let a stale "closed" value re-hide the onboarding fold).
function _initExtensionPersistence() {
  const panel = document.getElementById('ext-area');
  if (!panel || !window.bootstrap) return;
  const key = 'settings:collapse:ext-area';
  on(panel, 'show.bs.collapse', () => { try { localStorage.setItem(key, '1'); } catch (e) { /* ignore */ } });
  on(panel, 'hide.bs.collapse', () => { try { localStorage.setItem(key, '0'); } catch (e) { /* ignore */ } });
  if (panel.dataset.coldStart === 'true') return;  // cold start: keep server state
  let saved = null;
  try { saved = localStorage.getItem(key); } catch (e) { /* ignore */ }
  if (saved === '1' && !panel.classList.contains('show')) {
    try { window.bootstrap.Collapse.getOrCreateInstance(panel).show(); } catch (e) { /* ignore */ }
  } else if (saved === '0' && panel.classList.contains('show')) {
    try { window.bootstrap.Collapse.getOrCreateInstance(panel).hide(); } catch (e) { /* ignore */ }
  }
}

// Plan 2026-06-05-007 R15 — client-side filter for a large extension area.
// Hides cards whose channel name doesn't match, hides tier sub-groups that end
// up empty, and shows a "no match" message when nothing matches.
function _initExtensionFilter() {
  const input = document.querySelector('[data-action="filter-extension"]');
  const panel = document.getElementById('ext-area');
  if (!input || !panel) return;
  const noMatch = panel.querySelector('.ext-no-match');
  on(input, 'input', () => {
    const q = input.value.trim().toLowerCase();
    let anyVisible = false;
    panel.querySelectorAll('.ext-tier-group').forEach((group) => {
      let groupVisible = false;
      group.querySelectorAll('.dashboard-channel-card').forEach((card) => {
        const name = (card.getAttribute('data-channel') || '').toLowerCase();
        const match = !q || name.includes(q);
        card.hidden = !match;
        if (match) { groupVisible = true; anyVisible = true; }
      });
      group.hidden = !groupVisible;  // hide orphaned tier sub-headers
    });
    if (noMatch) noMatch.hidden = anyVisible;
  });
}

// ── boot ─────────────────────────────────────────────────────────
// Boot order is significant: _initActivePane must run before _initBindReopen
// so the target pane is display:block before scrollIntoView fires.
function _boot() {
  _initActions();
  _initSidebarNav();
  _initActivePane();        // must precede _initBindReopen + _openCollapseForHash
  _initLoadingOverlay();
  _initBindReopen();
  _openCollapseForHash();
  _initOverviewPersistence();
  _initExtensionPersistence();
  _initExtensionFilter();
  _restoreCachedBannerImage();
  on(window, 'hashchange', () => {
    const key = _hashToPaneKey(window.location.hash);
    if (key) {
      try { sessionStorage.setItem('settings:activePane', key); } catch (e) { /* ignore */ }
      showPane(key);
    }
    _openCollapseForHash();
  });
}

if (document.readyState === 'loading') {
  on(document, 'DOMContentLoaded', _boot);
} else {
  _boot();
}
