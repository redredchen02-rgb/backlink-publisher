// Per-link liveness drawer under the channel scorecard (Plan 2026-06-05-009 U3).
//
// Fetch-on-expand: a channel row's chevron toggles its detail row and loads that
// channel's per-link verdicts from GET /ce:health/scorecard/<channel>/links.
// Three states — pending / loaded (rows or empty) / error (with retry). Untrusted
// URLs go through textContent, never innerHTML. Re-fetches on every open so a
// single-link recheck (U4) is reflected without a stale cache.

import { fetchJson, postJson } from './lib/api.js';

const VERDICT = {
  alive: { label: 'ALIVE', cls: 'text-bg-success' },
  host_gone: { label: 'HOST GONE', cls: 'text-bg-danger' },
  link_stripped: { label: 'STRIPPED', cls: 'text-bg-danger' },
  dofollow_lost: { label: 'DOFOLLOW LOST', cls: 'text-bg-warning' },
  probe_error: { label: 'PROBE ERROR', cls: 'text-bg-secondary' },
};

function verdictBadge(verdict) {
  const v = VERDICT[verdict] || { label: String(verdict || '?'), cls: 'text-bg-light' };
  const span = document.createElement('span');
  span.className = 'badge ' + v.cls;
  span.textContent = v.label; // text label, not colour-only (a11y / R4)
  return span;
}

function fmtTs(ts) {
  return ts ? String(ts).replace('T', ' ').slice(0, 16) : '—';
}

function rowEl(link) {
  const tr = document.createElement('tr');
  if (link.live_url) tr.dataset.liveUrl = link.live_url; // key for in-place recheck

  const tdVerdict = document.createElement('td');
  tdVerdict.className = 'js-verdict-cell'; // replaced in place after a recheck
  tdVerdict.appendChild(verdictBadge(link.verdict));
  tr.appendChild(tdVerdict);

  const tdUrl = document.createElement('td');
  const a = document.createElement('a');
  a.href = link.live_url || '#';
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = link.live_url || '—'; // untrusted → textContent
  a.title = link.live_url || '';
  tdUrl.appendChild(a);
  tr.appendChild(tdUrl);

  const tdDf = document.createElement('td');
  tdDf.textContent = link.dofollow_state || '—';
  tr.appendChild(tdDf);

  const tdDrift = document.createElement('td');
  tdDrift.textContent = link.anchor_drift === true ? 'anchor drift' : '—';
  tr.appendChild(tdDrift);

  const tdTs = document.createElement('td');
  tdTs.className = 'text-muted js-ts-cell';
  tdTs.textContent = fmtTs(link.last_recheck_ts);
  tr.appendChild(tdTs);

  const tdAct = document.createElement('td');
  if (link.live_url) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-outline-primary recheck-link';
    btn.type = 'button';
    btn.textContent = 'Recheck';
    tdAct.appendChild(btn);
  }
  tr.appendChild(tdAct);

  return tr;
}

function renderRows(drawer, links) {
  drawer.replaceChildren();
  if (!links.length) {
    const empty = document.createElement('div');
    empty.className = 'text-muted py-2';
    empty.textContent = 'No rechecks recorded for this channel yet.';
    drawer.appendChild(empty);
    return;
  }
  const table = document.createElement('table');
  table.className = 'table table-sm mb-0';
  const thead = document.createElement('thead');
  thead.innerHTML =
    '<tr><th>Verdict</th><th>Published URL</th><th>Dofollow</th>' +
    '<th>Anchor</th><th>Last checked</th><th></th></tr>';
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  for (const link of links) tbody.appendChild(rowEl(link));
  table.appendChild(tbody);
  drawer.appendChild(table);
  // Single status line per drawer; the drawer container is aria-live=polite so
  // a screen reader announces which row updated.
  const status = document.createElement('div');
  status.className = 'scorecard-status text-muted small mt-1';
  drawer.appendChild(status);
}

async function recheckLink(btn) {
  const tr = btn.closest('tr');
  const liveUrl = tr && tr.dataset.liveUrl;
  if (!liveUrl || btn.disabled) return; // per-row lock — independent of other rows
  const drawer = tr.closest('.scorecard-drawer');
  const status = drawer && drawer.querySelector('.scorecard-status');
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = '…';
  try {
    const data = await postJson('/ce:health/scorecard/recheck-link', { live_url: liveUrl });
    // If a drawer re-fetch replaced this row mid-flight, the re-render already
    // shows fresh state — don't write into the detached row (lost update).
    if (!tr.isConnected) return;
    if (data && data.ok === true) {
      const vCell = tr.querySelector('.js-verdict-cell');
      if (vCell) vCell.replaceChildren(verdictBadge(data.verdict));
      const tCell = tr.querySelector('.js-ts-cell');
      if (tCell) tCell.textContent = fmtTs(data.last_recheck_ts);
      if (status) status.textContent = 'Rechecked ' + liveUrl + ' → ' + (data.verdict || '?');
    } else if (status) {
      status.textContent =
        'Recheck failed for ' + liveUrl + ' (' + ((data && data.error_code) || 'error') + ')';
    }
  } catch (_e) {
    if (status && tr.isConnected) status.textContent = 'Recheck failed for ' + liveUrl;
  } finally {
    if (btn.isConnected) {
      btn.disabled = false;
      btn.textContent = original;
    }
  }
}

function setState(drawer, text, withRetry) {
  drawer.replaceChildren();
  const div = document.createElement('div');
  div.className = 'text-muted py-2';
  div.textContent = text;
  if (withRetry) {
    const btn = document.createElement('button');
    btn.className = 'btn btn-sm btn-outline-secondary ms-2';
    btn.textContent = 'Retry';
    btn.addEventListener('click', () => load(drawer));
    div.appendChild(btn);
  }
  drawer.appendChild(div);
}

async function load(drawer) {
  const channel = drawer.dataset.channel;
  // Re-entry guard: a fast collapse/re-expand (or double-click) starts a newer
  // load; only the newest may paint, so a slow earlier fetch can't clobber it.
  const seq = (drawer._loadSeq || 0) + 1;
  drawer._loadSeq = seq;
  setState(drawer, 'Loading…', false);
  try {
    const data = await fetchJson(
      '/ce:health/scorecard/' + encodeURIComponent(channel) + '/links',
    );
    if (drawer._loadSeq !== seq) return; // superseded by a newer load
    if (!data || data.ok !== true) {
      setState(drawer, 'Could not load links.', true);
      return;
    }
    renderRows(drawer, data.links || []);
  } catch (_e) {
    if (drawer._loadSeq !== seq) return;
    setState(drawer, 'Could not load links.', true);
  }
}

function onExpand(btn) {
  const row = btn.closest('tr');
  if (!row) return;
  const detail = row.nextElementSibling;
  if (!detail || !detail.classList.contains('detail-row')) return;
  const open = detail.classList.toggle('d-none') === false;
  btn.setAttribute('aria-expanded', String(open));
  const icon = btn.querySelector('i');
  if (icon) icon.className = open ? 'bi bi-chevron-down' : 'bi bi-chevron-right';
  if (open) {
    const drawer = detail.querySelector('.scorecard-drawer');
    if (drawer) load(drawer); // re-fetch every open — no stale cache
  }
}

document.addEventListener('click', (ev) => {
  const expandBtn = ev.target.closest('[data-action="scorecard-expand"]');
  if (expandBtn) {
    ev.preventDefault();
    onExpand(expandBtn);
    return;
  }
  const recheckBtn = ev.target.closest('.recheck-link');
  if (recheckBtn) {
    ev.preventDefault();
    recheckLink(recheckBtn);
  }
});
