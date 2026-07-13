<script setup lang="ts">
// Vue counterpart of Unit 5's legacy nav-bar "report a problem" panel
// (webui_app/static/js/ui/error-report-entry.js) — Plan 2026-07-01-002
// Unit 7. Shared by two entry points via stores/reportPanel.ts:
//   - TopBar.vue's nav-bar button opens it with no reportId.
//   - Toast.vue's "补充说明" action opens it pre-filled with that toast's
//     reportId.
//
// Two submit paths (Unit 3 contract, webui_app/api/v1/error_reports.py):
//   - No reportId (nav-bar entry): POST /error-reports with
//     {message, source: 'manual', severity: 'error'} — the `reportId` KEY
//     must be absent entirely (never sent as null/false): the endpoint
//     treats ANY truthy reportId as "tied to an auto-captured error, apply
//     fingerprint dedup" and its absence as "manual report, always insert a
//     fresh row, never merge".
//   - Pre-filled reportId (from the toast path): PATCH
//     /error-reports/<reportId> with {description}.
//
// Explicit success (panel closes + confirmation toast via the existing
// notifications store) / explicit failure (inline error, panel stays open)
// — deliberately NOT the localStorage background-retry behavior
// lib/errorCapture.ts uses for auto-captured errors: a user who just typed
// a report and hit submit is watching for a result right now.
//
// classifyError() (not raw server text) backs the inline error message,
// same boundary useErrorToast.ts relies on — never splice server/exception
// text into user-facing copy. All template interpolation is Vue's default
// auto-escaping; no v-html anywhere in this file.
import { ref, watch } from 'vue'
import { sendJson } from '../api/client'
import { classifyError } from '../lib/errors'
import { useNotificationsStore } from '../stores/notifications'
import { useReportPanelStore } from '../stores/reportPanel'

// Unit 8 (running in parallel) is building the SPA route at this path —
// a literal string is all this component needs, no import from Unit 8's files.
const DASHBOARD_URL = '/app/error-reports'

const panel = useReportPanelStore()
const notify = useNotificationsStore()

const text = ref('')
const errorMsg = ref('')
const submitting = ref(false)

// Reset the form every time the panel transitions from closed -> open, so
// stale text/errors from a prior use never leak into the next one.
watch(
  () => panel.isOpen,
  (open) => {
    if (!open) return
    text.value = ''
    errorMsg.value = ''
  },
)

function onCancel(): void {
  panel.close()
}

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  const trimmed = text.value.trim()
  if (!trimmed) {
    errorMsg.value = '请输入内容后再提交。'
    return
  }
  errorMsg.value = ''
  submitting.value = true
  try {
    if (panel.reportId != null) {
      await sendJson('PATCH', `/error-reports/${encodeURIComponent(String(panel.reportId))}`, {
        description: trimmed,
      })
      notify.push('补充说明已提交，感谢您的反馈。', 'success')
    } else {
      // No `reportId` key at all — see module docstring above.
      await sendJson('POST', '/error-reports', {
        message: trimmed,
        source: 'manual',
        severity: 'error',
      })
      notify.push('问题反馈已提交，感谢您的报告。', 'success')
    }
    panel.close()
  } catch (e) {
    // Explicit inline failure state — panel stays open, nothing is
    // buffered for a background retry.
    errorMsg.value = classifyError(e).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div
    v-if="panel.isOpen"
    class="report-panel"
    role="dialog"
    aria-modal="true"
    aria-label="回报问题"
  >
    <div class="report-panel__header">
      <span class="report-panel__title">{{ panel.reportId != null ? '补充说明' : '回报问题' }}</span>
      <button type="button" class="report-panel__close" aria-label="关闭面板" @click="onCancel">×</button>
    </div>
    <div class="report-panel__body">
      <textarea
        v-model="text"
        class="report-panel__input"
        rows="4"
        :placeholder="panel.reportId != null ? '请补充这个问题的更多细节…' : '请描述您遇到的问题…'"
        aria-label="问题描述"
      />
      <div v-if="errorMsg" class="report-panel__error" role="alert">{{ errorMsg }}</div>
      <a :href="DASHBOARD_URL" class="report-panel__dashboard-link">查看完整错误报告仪表板</a>
      <div class="report-panel__actions">
        <button type="button" class="report-panel__cancel" :disabled="submitting" @click="onCancel">取消</button>
        <button type="button" class="report-panel__submit" :disabled="submitting" @click="onSubmit">
          {{ submitting ? '提交中…' : '提交' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-panel {
  position: fixed;
  top: var(--space-4);
  right: var(--space-4);
  z-index: 1300;
  width: 22rem;
  max-width: calc(100vw - 2 * var(--space-4));
  background: var(--surface-overlay);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-glass);
  color: var(--text-primary);
}
.report-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3);
  border-bottom: 1px solid var(--border);
}
.report-panel__title {
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-base);
}
.report-panel__close {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--text-lg);
  line-height: 1;
  padding: 0;
}
.report-panel__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
}
.report-panel__input {
  width: 100%;
  box-sizing: border-box;
  padding: var(--control-pad-y) var(--control-pad-x);
  font-family: inherit;
  font-size: var(--text-sm);
  resize: vertical;
}
.report-panel__error {
  color: var(--danger);
  font-size: var(--text-sm);
}
.report-panel__dashboard-link {
  font-size: var(--text-sm);
  color: var(--info);
}
.report-panel__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
