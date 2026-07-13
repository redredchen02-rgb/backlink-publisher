/**
 * Batch-campaign page — draft/publish mode toggle.
 *
 * Replaces the inline `onclick="setMode(...)"` handlers + the `setMode` global that
 * violated the enforced anti-rot rule (audit [41]). The mode tabs carry `data-mode`;
 * a single delegated click listener toggles the active tab and syncs the hidden
 * `#mode-input` the form submits.
 */
import { delegate } from './lib/dom.js';

function setMode(mode) {
    document.querySelectorAll('.mode-tab').forEach((tab) => {
        tab.classList.toggle('active', tab.dataset.mode === mode);
    });
    const input = document.getElementById('mode-input');
    if (input) input.value = mode;
}

delegate(document, 'click', '.mode-tab[data-mode]', (e, el) => {
    setMode(el.dataset.mode);
});
