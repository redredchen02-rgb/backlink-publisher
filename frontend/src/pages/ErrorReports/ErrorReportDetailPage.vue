<script setup lang="ts">
// Error-report detail drill-down — Plan 2026-07-01-002 Unit 8 (R5).
//
// Deliberately its own sub-route (/app/error-reports/:id), not a modal/drawer:
// this codebase has no existing modal/drawer component to reuse, and a
// sub-route is URL-shareable (an operator can hand a specific report's link
// to another operator) and works fine on narrow screens.
//
// This page's "add detail" action is the persistent R2 backup path into the
// SAME PATCH /api/v1/error-reports/<id> endpoint Unit 7's toast-triggered
// panel uses — it does NOT share code with ReportProblemPanel.vue. Even after
// the originating toast is long gone, an operator can still open this page
// (e.g. from the list) and attach a description.
//
// All report content (message/stack/url/user_description) renders through
// Vue's default {{ }} interpolation — NEVER v-html — so HTML-looking
// characters in a report render as literal text, never as parsed markup.
//
// Status mutation write-through: on a successful PATCH we write the response
// directly into this page's own query cache (mirrors HistoryPage.vue /
// SitesPage.vue's "response replaces cache" convention) AND invalidate the
// list page's query key prefix so ErrorReportsPage.vue picks up the new
// status without a full reload — TanStack Query's default prefix matching
// covers every filtered variant of the list query.
import { computed, ref } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  getErrorReport,
  updateErrorReport,
  type ErrorReportItem,
  type ErrorReportStatus,
} from '../../api/errorReports'
import StateBlock from '../../components/StateBlock.vue'
import StatusBadge from '../../components/StatusBadge.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'
import { useRowReportLinksStore } from '../../stores/rowReportLinks'

const LIST_KEY_PREFIX = ['error-reports'] as const

const STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  acknowledged: '已确认',
  resolved: '已解决',
}

const route = useRoute()
const router = useRouter()
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const rowReportLinks = useRowReportLinksStore()

const reportId = computed(() => String((route.params as Record<string, string>).id ?? ''))
const detailKey = computed(() => ['error-report', reportId.value] as const)

const query = useQuery({
  queryKey: detailKey,
  queryFn: () => getErrorReport(reportId.value),
  enabled: computed(() => !!reportId.value),
})

const report = computed<ErrorReportItem | null>(() => query.data.value ?? null)

// ── W10 "回到来源" (back to source) ──────────────────────────────────────
//
// Two tiers, in order of precision — see stores/rowReportLinks.ts's
// docstring for exactly why a row-level link is only ever available in the
// first tier:
//   1. rowReportLinks still remembers (THIS SPA session only) that this
//      exact report id was produced by a specific row's failed action —
//      navigate straight back to that row and highlight it.
//   2. Otherwise, fall back to the page-level `url` the report itself
//      captured at the moment the error happened (lib/errorCapture.ts's
//      `currentUrl()`) — same-origin path + query only, no row target. This
//      covers reports from a previous session/reload, where no row-level
//      correlation could ever have survived.
// If neither is available (report.url missing, cross-origin, or malformed),
// there is genuinely nothing to navigate back to — the button/link is
// hidden entirely rather than pointing somewhere wrong.
function safePathFromUrl(url: string | undefined): string | null {
  if (!url) return null
  try {
    const u = new URL(url, window.location.origin)
    if (u.origin !== window.location.origin) return null
    return u.pathname + u.search
  } catch {
    return null
  }
}

const rowLink = computed(() => (report.value ? rowReportLinks.linkForReport(report.value.id) : undefined))

const backTarget = computed<{ name: string; query: Record<string, string> } | { path: string } | null>(() => {
  if (rowLink.value) {
    return { name: rowLink.value.routeName, query: { highlight: rowLink.value.rowId } }
  }
  const path = safePathFromUrl(report.value?.url)
  return path ? { path } : null
})

const backTargetLabel = computed(() => (rowLink.value ? '回到来源并定位记录' : '回到来源页面'))

function goToSource(): void {
  const target = backTarget.value
  if (!target) return
  if ('name' in target) {
    void router.push({ name: target.name, query: target.query })
  } else {
    void router.push(target.path)
  }
}

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return report.value ? 'ready' : 'empty'
})

const statusBusy = ref(false)

async function writeThrough(updated: ErrorReportItem): Promise<void> {
  qc.setQueryData(detailKey.value, updated)
  // The exact list variant this row belongs to (which filter combination)
  // isn't known here, so invalidate every list query sharing the
  // ['error-reports', ...] prefix rather than guessing one filter set.
  await qc.invalidateQueries({ queryKey: LIST_KEY_PREFIX })
}

async function setStatus(status: ErrorReportStatus): Promise<void> {
  if (statusBusy.value || !report.value) return
  statusBusy.value = true
  try {
    const updated = await updateErrorReport(report.value.id, { status })
    await writeThrough(updated)
    notify.push(`已标记为${STATUS_LABELS[status] ?? status}`, 'success')
  } catch (e) {
    toastError(e)
  } finally {
    statusBusy.value = false
  }
}

// ── "add detail" / 补充说明 (persistent R2 path) ─────────────────────────────
const descriptionDraft = ref('')
const descriptionSaving = ref(false)
const descriptionError = ref('')

async function submitDescription(): Promise<void> {
  const text = descriptionDraft.value.trim()
  if (!text) {
    descriptionError.value = '请输入补充说明内容'
    return
  }
  if (descriptionSaving.value || !report.value) return
  descriptionSaving.value = true
  descriptionError.value = ''
  try {
    const updated = await updateErrorReport(report.value.id, { description: text })
    await writeThrough(updated)
    descriptionDraft.value = ''
    notify.push('补充说明已提交', 'success')
  } catch (e) {
    descriptionError.value = '提交失败，请重试。'
    toastError(e)
  } finally {
    descriptionSaving.value = false
  }
}

function fmtTime(iso: string | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isFinite(d.getTime()) ? d.toLocaleString('zh-CN') : iso
}
</script>

<template>
  <section class="error-report-detail">
    <header class="error-report-detail__head">
      <RouterLink to="/error-reports" class="back-link">← 返回错误报告列表</RouterLink>
      <h1>错误报告详情</h1>
    </header>

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      empty-text="找不到这条错误报告。"
      @retry="query.refetch()"
    >
      <template v-if="report">
        <div v-if="backTarget" class="back-to-source">
          <button type="button" class="back-to-source__btn" @click="goToSource">
            ← {{ backTargetLabel }}
          </button>
        </div>
        <p v-else class="muted back-to-source-missing">
          暂无法定位来源页面（该报告未记录可用的来源地址）。
        </p>

        <div class="summary">
          <StatusBadge :status="report.status" :label="STATUS_LABELS[report.status]" />
          <span v-if="report.severity" class="chip">严重度：{{ report.severity }}</span>
          <span v-if="report.source" class="chip">来源：{{ report.source }}</span>
          <span class="chip">发生次数：{{ report.occurrences ?? 1 }}</span>
        </div>

        <dl class="meta">
          <div><dt>首次发生</dt><dd>{{ fmtTime(report.created_at) }}</dd></div>
          <div><dt>最后发生</dt><dd>{{ fmtTime(report.last_seen_at) }}</dd></div>
          <div v-if="report.url"><dt>网址</dt><dd class="mono">{{ report.url }}</dd></div>
        </dl>

        <section v-if="report.message" class="block">
          <h2>消息</h2>
          <p class="mono">{{ report.message }}</p>
        </section>

        <section v-if="report.stack" class="block">
          <h2>堆栈</h2>
          <pre class="mono stack">{{ report.stack }}</pre>
        </section>

        <!-- Paired with the negative case: this section only renders when
             user_description is present, so its absence is never rendered
             as an empty/blank heading. -->
        <section v-if="report.user_description" class="block user-description">
          <h2>用户补充说明</h2>
          <p class="mono">{{ report.user_description }}</p>
        </section>

        <section class="actions">
          <h2>标记状态</h2>
          <div class="status-buttons">
            <button
              type="button"
              :disabled="statusBusy || report.status === 'acknowledged'"
              @click="setStatus('acknowledged')"
            >
              标记已确认
            </button>
            <button
              type="button"
              :disabled="statusBusy || report.status === 'resolved'"
              @click="setStatus('resolved')"
            >
              标记已解决
            </button>
          </div>
        </section>

        <section class="add-detail">
          <h2>补充说明</h2>
          <p class="muted">即使提示消息早已消失，也可以在这里为这条报告补充情境说明。</p>
          <textarea
            v-model="descriptionDraft"
            rows="3"
            placeholder="描述发生时的情境、重现步骤等…"
            aria-label="补充说明内容"
          />
          <p v-if="descriptionError" class="field-error" role="alert">{{ descriptionError }}</p>
          <button type="button" :disabled="descriptionSaving" @click="submitDescription">
            提交补充说明
          </button>
        </section>
      </template>
    </StateBlock>
  </section>
</template>

<style scoped>
.error-report-detail {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.error-report-detail__head {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.back-link {
  color: var(--primary);
  text-decoration: none;
  font-size: var(--text-sm, 0.85rem);
}
.back-link:hover {
  text-decoration: underline;
}
.back-to-source__btn {
  background: none;
  border: none;
  color: var(--primary);
  cursor: pointer;
  padding: 0;
  font: inherit;
  font-size: var(--text-sm, 0.85rem);
  text-decoration: underline;
}
.back-to-source-missing {
  font-size: var(--text-sm, 0.85rem);
}
.summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}
.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: 0.5rem 1rem;
  margin: 0;
}
.meta div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.meta dt {
  font-size: var(--text-sm, 0.8rem);
  color: var(--text-secondary);
}
.meta dd {
  margin: 0;
}
.block {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.block h2,
.actions h2,
.add-detail h2 {
  font-size: var(--text-lg, 1rem);
  margin: 0;
}
.mono {
  font-family: ui-monospace, monospace;
  white-space: pre-wrap;
  word-break: break-word;
}
.stack {
  background: var(--surface-raised);
  padding: 0.6rem;
  border-radius: var(--radius-md);
  max-height: 20rem;
  overflow: auto;
}
.actions,
.add-detail {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.status-buttons {
  display: flex;
  gap: 0.5rem;
}
textarea {
  padding: 0.5rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  color: inherit;
  font: inherit;
  resize: vertical;
}
.field-error {
  color: var(--danger);
  font-size: var(--text-sm, 0.85rem);
}
.muted {
  color: var(--text-secondary);
}
</style>
