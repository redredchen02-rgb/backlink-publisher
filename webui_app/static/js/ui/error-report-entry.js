/**
 * ui/error-report-entry.js — nav-bar "report a problem" entry + panel (Unit 5, R2/R3).
 *
 * The button itself is static markup in base.html (`#reportProblemBtn`,
 * inside `.app-topbar__actions` — the REAL topbar actions container; see
 * notifications.js's own `createBadge()` for the known-dead
 * `.global-nav__actions` selector this module deliberately does not repeat).
 * This module looks that button up SCOPED THROUGH `.app-topbar__actions`
 * (not a bare `document.getElementById`), so a future selector regression
 * fails loudly (button never wired) instead of silently finding it via the
 * wrong container. It then wires up a single shared panel: a free-text
 * textarea + submit, plus a link to the full SPA error-reports dashboard.
 *
 * The SAME panel is reused by ui/toast.js's "补充说明" (add detail) action on
 * a reportId-bearing toast: that module dispatches `app:report-detail-request`
 * (a CustomEvent on document; kept here as a literal string, not imported,
 * for the same decoupling reason notifications.js/toast.js keep `app:notify`
 * as a literal on both sides — this module must not force toast.js's module
 * body to execute out of its own <script> tag order) carrying
 * `detail.reportId`; this module listens for it and opens the panel
 * pre-filled, switching the submit path from POST to PATCH.
 *
 * Two distinct submit paths (Unit 3 contract, webui_app/api/v1/error_reports.py):
 *   - No reportId (nav-bar entry): POST /api/v1/error-reports with
 *     {message, source: 'manual', severity: 'error'} — the `reportId` KEY
 *     must be absent entirely (never sent as null/false): the endpoint
 *     treats ANY truthy reportId as "tied to an auto-captured error, apply
 *     fingerprint dedup", and its absence as "manual report, always insert a
 *     fresh row, never merge".
 *   - Pre-filled reportId (from a toast's "add more detail" action): PATCH
 *     /api/v1/error-reports/<reportId> with {description}.
 *
 * On submit: an explicit success state (panel closes + a confirmation toast
 * via notifications.js's exported live center) or an explicit failure state
 * (inline error message inside the panel, panel stays open) — deliberately
 * NOT the localStorage background-retry behaviour ui/error-capture.js uses
 * for auto-captured errors. A user who just typed a report and hit submit is
 * watching for a result right now; silently deferring it to a background
 * retry would be a UX regression, not resilience.
 *
 * All rendering uses createElement/textContent (never innerHTML) on
 * captured or user-typed content, per this codebase's frontend anti-rot
 * rules. Mirrors notifications.js's el() helper and its panel
 * open/close-on-outside-click/Escape-to-close pattern.
 */
import { readCsrf } from '../lib/api.js';
import { getNotificationCenter } from '../notifications.js';
import { classifyError } from './errors.js';

const POST_URL = '/api/v1/error-reports';
const EXPORT_URL = '/api/v1/error-reports/export-bundle';
const DASHBOARD_URL = '/app/error-reports';
const MOUNT_SELECTOR = '.app-topbar__actions';
const BUTTON_ID = 'reportProblemBtn';

// Mirrors ui/toast.js's own REPORT_DETAIL_EVENT constant — see that file's
// docstring for why this stays a literal instead of an import.
const REPORT_DETAIL_EVENT = 'app:report-detail-request';

function patchUrl(reportId) {
    return `/api/v1/error-reports/${encodeURIComponent(reportId)}`;
}

// el() — createElement builder mirroring notifications.js's helper (no
// innerHTML, ever).
function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
        if (value == null || value === false) continue;
        if (key === 'text') node.textContent = value;
        else if (key === 'class') node.className = value;
        else node.setAttribute(key, value);
    }
    for (const child of children) {
        if (child == null) continue;
        node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return node;
}

// ── pure helpers (no DOM) ────────────────────────────────────────────────────

function isBlankInput(text) {
    return !text || !String(text).trim();
}

function buildManualReportBody(text) {
    // No `reportId` key AT ALL — see module docstring.
    return { message: String(text).trim(), source: 'manual', severity: 'error' };
}

function buildDescriptionBody(text) {
    return { description: String(text).trim() };
}

// ── submission ───────────────────────────────────────────────────────────────

async function postManualReport(text) {
    const resp = await fetch(POST_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
        body: JSON.stringify(buildManualReportBody(text)),
    });
    if (!resp.ok) {
        const err = new Error(`manual report submit failed: HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return resp.json().catch(() => ({}));
}

async function postExportBundle(description) {
    const resp = await fetch(EXPORT_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
        body: JSON.stringify({ description }),
    });
    if (!resp.ok) {
        const err = new Error(`bundle export failed: HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return resp.json();
}

/** Client-side download of the returned markdown — no extra endpoint; the
 *  server has already persisted its own copy (report_path in the response). */
function downloadMarkdown(markdown) {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = el('a', { href: url, download: `bug-report-${Date.now()}.md` });
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

async function patchReportDescription(reportId, text) {
    const resp = await fetch(patchUrl(reportId), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': readCsrf() },
        body: JSON.stringify(buildDescriptionBody(text)),
    });
    if (!resp.ok) {
        const err = new Error(`report description update failed: HTTP ${resp.status}`);
        err.status = resp.status;
        throw err;
    }
    return resp.json().catch(() => ({}));
}

function notifySuccess(message) {
    // getNotificationCenter() is notifications.js's documented export "for
    // consumers that need the live center" — this is the boundary rule
    // ui/errors.js's own docstring states: transient action feedback (a
    // submit that succeeded) goes via notifications.js, not a bespoke toast.
    const center = getNotificationCenter();
    if (center) center.success(message);
}

// ── panel ──────────────────────────────────────────────────────────────────

class ReportPanel {
    constructor() {
        this.reportId = null;
        this.isOpen = false;
        this._triggerEl = null;
        this._build();
        this._bindGlobalEvents();
    }

    _build() {
        this.titleEl = el('span', { class: 'error-report-panel__title', text: '回报问题' });
        const closeBtn = el('button', {
            type: 'button', class: 'error-report-panel__close', 'aria-label': '关闭面板',
        }, [el('i', { class: 'bi bi-x' })]);
        closeBtn.addEventListener('click', () => this.close());
        const header = el('div', { class: 'error-report-panel__header' }, [this.titleEl, closeBtn]);

        this.textarea = el('textarea', {
            class: 'error-report-panel__input',
            rows: '4',
            placeholder: '请描述您遇到的问题…',
            'aria-label': '问题描述',
        });

        this.errorBox = el('div', { class: 'error-report-panel__error', role: 'alert' });
        this.errorBox.hidden = true;

        const dashboardLink = el('a', {
            href: DASHBOARD_URL,
            class: 'error-report-panel__dashboard-link',
            text: '查看完整错误报告仪表板',
        });

        const cancelBtn = el('button', {
            type: 'button', class: 'error-report-panel__cancel', text: '取消',
        });
        cancelBtn.addEventListener('click', () => this.close());

        this.submitBtn = el('button', {
            type: 'button', class: 'error-report-panel__submit', text: '提交',
        });
        this.submitBtn.addEventListener('click', () => this._submit());

        // 匯出診斷包 (Plan 2026-07-09-002): POSTs the description to the
        // export-bundle endpoint, which assembles a secret-redacted MD+JSON
        // bundle server-side (shared builder with the bp-report-bug CLI) and
        // returns the markdown for a client-side download.
        this.exportBtn = el('button', {
            type: 'button', class: 'error-report-panel__export', text: '匯出診斷包',
        });
        this.exportBtn.addEventListener('click', () => this._exportBundle());

        const actions = el('div', { class: 'error-report-panel__actions' }, [
            this.exportBtn, cancelBtn, this.submitBtn,
        ]);
        const body = el('div', { class: 'error-report-panel__body' }, [
            this.textarea, this.errorBox, dashboardLink, actions,
        ]);

        this.panel = el('div', {
            class: 'error-report-panel', role: 'dialog', 'aria-label': '回报问题',
        }, [header, body]);
        this.panel.hidden = true;

        document.body.appendChild(this.panel);
    }

    _bindGlobalEvents() {
        // Close on outside click — mirrors notifications.js's NotificationCenter
        // pattern, generalized to "whichever element triggered open()" rather
        // than a single fixed badge, since this panel has two possible
        // triggers (the topbar button, or a toast's "补充说明" button).
        document.addEventListener('click', (e) => {
            if (!this.isOpen) return;
            const insidePanel = this.panel.contains(e.target);
            const onTrigger = this._triggerEl ? this._triggerEl.contains(e.target) : false;
            if (!insidePanel && !onTrigger) this.close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isOpen) this.close();
        });
    }

    open({ reportId = null, triggerEl = null } = {}) {
        this.reportId = reportId || null;
        this._triggerEl = triggerEl || null;
        this.textarea.value = '';
        this._hideError();
        this.titleEl.textContent = this.reportId ? '补充说明' : '回报问题';
        this.textarea.placeholder = this.reportId
            ? '请补充这个问题的更多细节…'
            : '请描述您遇到的问题…';
        this.panel.hidden = false;
        this.isOpen = true;
        try { this.textarea.focus(); } catch { /* focus not available everywhere */ }
    }

    close() {
        this.panel.hidden = true;
        this.isOpen = false;
    }

    _showError(message) {
        this.errorBox.textContent = message;
        this.errorBox.hidden = false;
    }

    _hideError() {
        this.errorBox.textContent = '';
        this.errorBox.hidden = true;
    }

    async _submit() {
        const text = this.textarea.value;
        if (isBlankInput(text)) {
            this._showError('请输入内容后再提交。');
            return;
        }
        this._hideError();
        try {
            if (this.reportId) {
                await patchReportDescription(this.reportId, text);
                this.close();
                notifySuccess('补充说明已提交，感谢您的反馈。');
            } else {
                await postManualReport(text);
                this.close();
                notifySuccess('问题反馈已提交，感谢您的报告。');
            }
        } catch (err) {
            // Explicit inline failure state — panel stays open, nothing is
            // buffered to localStorage. See module docstring.
            this._showError(classifyError(err).message);
        }
    }

    async _exportBundle() {
        // Description is optional for a bundle (the endpoint builds a general
        // diagnostic snapshot when no error source is given) — no blank guard.
        this._hideError();
        this.exportBtn.disabled = true;
        this.exportBtn.textContent = '正在生成…';
        try {
            const result = await postExportBundle(this.textarea.value);
            if (result && typeof result.markdown === 'string') {
                downloadMarkdown(result.markdown);
            }
            this.close();
            notifySuccess('诊断包已生成并下载，可直接交给 coding agent。');
        } catch (err) {
            this._showError(classifyError(err).message);
        } finally {
            this.exportBtn.disabled = false;
            this.exportBtn.textContent = '匯出診斷包';
        }
    }
}

// ── mount ──────────────────────────────────────────────────────────────────

function initErrorReportEntry() {
    // Built unconditionally: the panel also serves the toast "补充说明" path
    // below, which must keep working even if the topbar button lookup ever
    // fails for an unrelated reason.
    const panel = new ReportPanel();

    const container = document.querySelector(MOUNT_SELECTOR);
    const button = container && container.querySelector(`#${BUTTON_ID}`);
    if (button) {
        button.addEventListener('click', () => panel.open({ triggerEl: button }));
    }

    document.addEventListener(REPORT_DETAIL_EVENT, (e) => {
        const reportId = e && e.detail && e.detail.reportId;
        if (!reportId) return;
        panel.open({ reportId });
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initErrorReportEntry);
} else {
    initErrorReportEntry();
}
