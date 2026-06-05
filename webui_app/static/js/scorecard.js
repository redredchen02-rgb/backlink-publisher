// Per-link liveness drawer under the channel scorecard (Plan 2026-06-05-009 U3).
//
// Fetch-on-expand: a channel row's chevron toggles its detail row and loads that
// channel's per-link verdicts from GET /ce:health/scorecard/<channel>/links.
// Three states — pending / loaded (rows or empty) / error (with retry). Untrusted
// URLs go through textContent, never innerHTML. Re-fetches on every open so a
// single-link recheck (U4) is reflected without a stale cache.

import { fetchJson } from './lib/api.js';

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

  const tdVerdict = document.createElement('td');
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
  tdTs.className = 'text-muted';
  tdTs.textContent = fmtTs(link.last_recheck_ts);
  tr.appendChild(tdTs);

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
    '<th>Anchor</th><th>Last checked</th></tr>';
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  for (const link of links) tbody.appendChild(rowEl(link));
  table.appendChild(tbody);
  drawer.appendChild(table);
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
  setState(drawer, 'Loading…', false);
  try {
    const data = await fetchJson(
      '/ce:health/scorecard/' + encodeURIComponent(channel) + '/links',
    );
    if (!data || data.ok !== true) {
      setState(drawer, 'Could not load links.', true);
      return;
    }
    renderRows(drawer, data.links || []);
  } catch (_e) {
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
  const btn = ev.target.closest('[data-action="scorecard-expand"]');
  if (btn) {
    ev.preventDefault();
    onExpand(btn);
  }
});
