/**
 * ui/nav-badge.js — sidebar anomaly badge (U7).
 *
 * Single fail-open fetch to /api/monitor-hub; shows the count of anomalies
 * (danger + warning cards) on the 聚合 sidebar item. Hidden at zero (a count of
 * "0" reads as noise — design-lens zero-count rule). No polling: it reflects the
 * state at page load, same cadence as the rest of the shell. The badge carries
 * an accessible name so a screen reader announces "监控聚合：N 项异常" rather
 * than a bare glyph + number.
 */
import { fetchJson } from '../lib/api.js';

async function updateAnomalyBadge() {
    const badge = document.getElementById('navAnomalyBadge');
    if (!badge) return;
    let data;
    try {
        data = await fetchJson('/api/monitor-hub');
    } catch {
        return; // fail-open: leave the badge hidden on any error
    }
    const count = (data && data.ok !== false && Number(data.anomaly_count)) || 0;
    if (count > 0) {
        badge.textContent = String(count);
        badge.setAttribute('aria-label', `监控聚合：${count} 项异常`);
        badge.hidden = false;
    } else {
        badge.textContent = '';
        badge.removeAttribute('aria-label');
        badge.hidden = true;
    }
}

updateAnomalyBadge();
