// /ce:health maintenance actions (Plan 2026-06-03-004 Phase 2 — U5/U6/U7).
//
// Delegated click handler for the Platform last-state panel's action buttons.
// No inline on* handlers (anti-rot rule 1); CSRF travels via postJson's
// X-CSRFToken header read fresh per call (rule 4); all DOM writes use
// textContent — never innerHTML (rule 3).

import { postJson } from './lib/api.js';

const ENDPOINTS = {
  'health-pause': '/ce:health/pause',
  'health-reverify': '/ce:health/reverify',
  'health-circuit-reset': '/ce:health/circuit-reset',
};

function statusEl(btn) {
  const row = btn.closest('[data-platform-row]');
  return row ? row.querySelector('[data-cell="action-status"]') : null;
}

function setStatus(btn, text, cls) {
  const el = statusEl(btn);
  if (!el) return;
  el.textContent = text;
  el.className = 'small ms-1 ' + (cls || 'text-muted');
}

function bodyFor(action, btn) {
  const platform = btn.dataset.platform;
  if (action === 'health-pause') {
    // Toggle: data-paused reflects the current server state.
    return { platform, paused: btn.dataset.paused !== '1' };
  }
  return { platform };
}

async function handle(action, btn) {
  const url = ENDPOINTS[action];
  if (!url) return;
  btn.disabled = true;
  setStatus(btn, '…', 'text-muted');
  try {
    const res = await postJson(url, bodyFor(action, btn));
    if (!res || res.ok === false) {
      setStatus(btn, '✗ ' + ((res && res.reason) || 'failed'), 'text-danger');
      return;
    }
    if (action === 'health-pause') {
      const paused = res.paused === true;
      btn.dataset.paused = paused ? '1' : '0';
      btn.textContent = paused ? 'Resume' : 'Pause';
      setStatus(btn, paused ? '✓ paused' : '✓ resumed', 'text-success');
    } else if (action === 'health-reverify') {
      setStatus(
        btn,
        res.ready ? '✓ ready' : '✗ ' + (res.reason || 'not ready'),
        res.ready ? 'text-success' : 'text-warning',
      );
    } else if (action === 'health-circuit-reset') {
      setStatus(btn, '✓ reset', 'text-success');
    }
  } catch (err) {
    setStatus(btn, '✗ error', 'text-danger');
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener('click', (ev) => {
  const btn = ev.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  if (action in ENDPOINTS) {
    ev.preventDefault();
    handle(action, btn);
  }
});
