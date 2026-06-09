// Sites page module — quick-publish button handler.
import { fetchJson, postJson } from './lib/api.js';

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
