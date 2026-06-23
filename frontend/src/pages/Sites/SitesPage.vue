<script setup lang="ts">
// Work-themed site config page — Plan 2026-06-18-002 U7 (sites page).
//
// Replaces the legacy Jinja /sites form (render / 302 + flash). Three concerns:
//  1. Config form (①②③): main/list/work URLs + anchor pools + gen params. Submit
//     → POST /sites/save. A 422 carries field-level errors[] (rendered inline);
//     success surfaces the server-derived field names as an "autofilled" notice.
//  2. Autopilot table (④): per-site enable switch + interval; toggle → POST
//     /sites/autopilot, returns the refreshed list (written into the cache).
//  3. Read-only widgets (⑤): plan-gap weekly summary + citation-share alert.
//
// The embedded batch-operations table is intentionally OUT of scope (its own
// "batch" unit). Failures go through classifyError → toast (never raw text).
import { computed, reactive, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  getSiteForm,
  getSitesWidgets,
  listSites,
  saveSite,
  scrapePreview,
  setAutopilot,
  type SiteForm,
  type SiteItem,
} from '../../api/sites'
import { ApiError } from '../../api/client'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'
import { classifyError } from '../../lib/errors'

const SITES_KEY = ['sites']
const WIDGETS_KEY = ['sites', 'widgets']
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()

const sitesQuery = useQuery({ queryKey: SITES_KEY, queryFn: listSites })
const widgetsQuery = useQuery({ queryKey: WIDGETS_KEY, queryFn: getSitesWidgets })
const items = computed<SiteItem[]>(() => sitesQuery.data.value?.items ?? [])

const listState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (sitesQuery.isPending.value) return 'loading'
  if (sitesQuery.isError.value) return 'error'
  return items.value.length ? 'ready' : 'empty'
})

// ── config form ─────────────────────────────────────────────────────────────
const emptyForm = (): SiteForm => ({
  main_url: '',
  list_url: '',
  work_urls: '',
  branded_pool: '',
  partial_pool: '',
  exact_pool: '',
  work_anchor_templates: '',
  count: '10',
  insecure_tls: false,
})
const form = reactive<SiteForm>(emptyForm())
const fieldErrors = reactive<Record<string, string>>({})
const autofilled = ref<string[]>([])
const savedDomain = ref('')
const saving = ref(false)

function clearErrors(): void {
  for (const k of Object.keys(fieldErrors)) delete fieldErrors[k]
}

async function onSave(): Promise<void> {
  if (saving.value) return
  saving.value = true
  clearErrors()
  autofilled.value = []
  try {
    const r = await saveSite({ ...form })
    qc.setQueryData(SITES_KEY, { items: r.items })
    savedDomain.value = r.saved_domain
    autofilled.value = r.autofilled
    notify.push(`已保存站点：${r.saved_domain}`, 'info')
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const errs = (e.payload as { errors?: { field: string; message: string }[] })?.errors ?? []
      for (const { field, message } of errs) fieldErrors[field] = message
      if (errs.length) {
        saving.value = false
        return
      }
    }
    toastError(e)
  } finally {
    saving.value = false
  }
}

async function onEdit(mainUrl: string): Promise<void> {
  try {
    const { form: loaded } = await getSiteForm(mainUrl)
    if (loaded) {
      Object.assign(form, loaded)
      clearErrors()
      autofilled.value = []
      notify.push(`已载入配置：${mainUrl}`, 'info')
    }
  } catch (e) {
    toastError(e)
  }
}

// ── scrape preview (work-URL metadata helper) ─────────────────────────────────
const previewUrl = ref('')
const preview = ref<string>('')
const previewing = ref(false)
async function onPreview(): Promise<void> {
  if (!previewUrl.value.trim()) {
    notify.push('请先填入要预览的作品 URL', 'warning')
    return
  }
  previewing.value = true
  preview.value = ''
  try {
    const r = await scrapePreview(previewUrl.value.trim())
    preview.value =
      r.status === 'ok'
        ? `title: ${r.title}\ndescription: ${r.description}\nh1: ${r.h1}`
        : `无法读取：${r.reason ?? '未知原因'}`
  } catch (e) {
    toastError(e)
  } finally {
    previewing.value = false
  }
}

// ── autopilot ────────────────────────────────────────────────────────────────
const PRESET_INTERVALS = new Set([86400, 604800])
// Per-row interval-select state ('86400' | '604800' | 'custom') + custom seconds.
const intervalChoice = reactive<Record<string, string>>({})
const customSeconds = reactive<Record<string, number>>({})
const togglingUrl = ref<string | null>(null)

function choiceFor(site: SiteItem): string {
  return intervalChoice[site.main_url] ?? (PRESET_INTERVALS.has(site.autopilot_interval)
    ? String(site.autopilot_interval)
    : 'custom')
}
function customFor(site: SiteItem): number {
  return customSeconds[site.main_url] ?? site.autopilot_interval
}
function intervalForToggle(site: SiteItem): number {
  const choice = choiceFor(site)
  if (choice === 'custom') return customFor(site) || 86400
  return Number(choice) || 86400
}

function formatRelative(iso: string | null): string | null {
  if (!iso) return null
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  if (!Number.isFinite(diff) || diff < 0) return '排程中…'
  if (diff < 3600) return `${Math.ceil(diff / 60)} 分钟后`
  if (diff < 86400) return `${Math.ceil(diff / 3600)} 小时后`
  return `${Math.ceil(diff / 86400)} 天后`
}

function rowStatus(site: SiteItem): { text: string; tone: 'ok' | 'warn' | 'muted' } {
  if (!site.autopilot_enabled) return { text: '—', tone: 'muted' }
  if (site.alert_pending) return { text: '⚠ 上次失败', tone: 'warn' }
  const rel = formatRelative(site.next_run_time_iso)
  return rel ? { text: `⏭ 下次：${rel}`, tone: 'ok' } : { text: '排程中…', tone: 'muted' }
}

async function onToggleAutopilot(site: SiteItem, enabled: boolean): Promise<void> {
  if (togglingUrl.value) return
  togglingUrl.value = site.main_url
  try {
    const r = await setAutopilot(site.main_url, enabled, enabled ? intervalForToggle(site) : 86400)
    qc.setQueryData(SITES_KEY, { items: r.items })
    notify.push(enabled ? '已开启 Autopilot' : '已停止 Autopilot', 'info')
  } catch (e) {
    toastError(e)
  } finally {
    togglingUrl.value = null
  }
}
</script>

<template>
  <section class="sites">
    <h1>站点配置</h1>

    <!-- ① ② ③ config form -->
    <form class="site-form" novalidate @submit.prevent="onSave">
      <p v-if="savedDomain" class="saved" role="status">✓ 已保存站点：{{ savedDomain }}</p>
      <div v-if="autofilled.length" class="autofilled" role="status">
        <strong>已自动派生：</strong>{{ autofilled.join('、') }}
        <span class="muted"> — 系统据 main_url 元数据派生；回到对应字段直接编辑即可覆盖。</span>
      </div>

      <fieldset>
        <legend>① URLs</legend>
        <label>
          main_url（品牌权重承接）
          <input v-model="form.main_url" type="text" placeholder="https://your-site.com/" />
          <span v-if="fieldErrors.main_url" class="field-error">{{ fieldErrors.main_url }}</span>
        </label>
        <label>
          list_url（作品发现源，可选）
          <input v-model="form.list_url" type="text" placeholder="https://your-site.com/list" />
          <span v-if="fieldErrors.list_url" class="field-error">{{ fieldErrors.list_url }}</span>
        </label>
        <label>
          work_urls（每行一个，可选）
          <textarea v-model="form.work_urls" rows="3" />
          <span v-if="fieldErrors.work_urls" class="field-error">{{ fieldErrors.work_urls }}</span>
        </label>
      </fieldset>

      <fieldset>
        <legend>② Anchor Pools（任一池留空将自动派生）</legend>
        <label>
          branded_pool
          <textarea v-model="form.branded_pool" rows="2" />
        </label>
        <div class="two-col">
          <label>
            partial_pool（70%）
            <textarea v-model="form.partial_pool" rows="2" />
          </label>
          <label>
            exact_pool（30%）
            <textarea v-model="form.exact_pool" rows="2" />
          </label>
        </div>
        <label>
          work_anchor_templates（{title} 占位符，留空用默认）
          <textarea v-model="form.work_anchor_templates" rows="2" />
        </label>
      </fieldset>

      <fieldset>
        <legend>③ Generation Params</legend>
        <div class="two-col">
          <label>
            count
            <input v-model="form.count" type="number" min="1" max="100" />
          </label>
          <label class="checkbox">
            <input v-model="form.insecure_tls" type="checkbox" />
            insecure_tls（仅目标站 TLS 故障时启用）
          </label>
        </div>
      </fieldset>

      <div class="form-actions">
        <button type="submit" class="primary" :disabled="saving">保存配置</button>
      </div>
    </form>

    <!-- scrape preview helper -->
    <fieldset class="preview-box">
      <legend>作品元数据预览</legend>
      <div class="preview-row">
        <input v-model="previewUrl" type="text" placeholder="https://your-site.com/work/1" aria-label="预览作品 URL" />
        <button type="button" :disabled="previewing" @click="onPreview">预览</button>
      </div>
      <pre v-if="preview" class="preview-out">{{ preview }}</pre>
    </fieldset>

    <!-- ④ autopilot -->
    <section class="autopilot">
      <h2>④ Autopilot 定时保活</h2>
      <StateBlock
        :state="listState"
        :error="sitesQuery.error.value"
        empty-text="尚无已配置站点"
        @retry="sitesQuery.refetch()"
      >
        <div class="data-table-wrap">
        <table class="ap-table data-table">
          <thead>
            <tr><th>标签</th><th>main_url</th><th>启用</th><th>间隔</th><th>状态</th><th /></tr>
          </thead>
          <tbody>
            <tr v-for="site in items" :key="site.main_url">
              <td>{{ site.label }}</td>
              <td class="col-url muted" :title="site.main_url">{{ site.main_url }}</td>
              <td>
                <input
                  type="checkbox"
                  role="switch"
                  :checked="site.autopilot_enabled"
                  :disabled="togglingUrl === site.main_url"
                  :aria-label="`启用 ${site.label} 的 Autopilot`"
                  @change="onToggleAutopilot(site, ($event.target as HTMLInputElement).checked)"
                />
              </td>
              <td>
                <select
                  :value="choiceFor(site)"
                  :aria-label="`${site.label} 保活间隔`"
                  @change="intervalChoice[site.main_url] = ($event.target as HTMLSelectElement).value"
                >
                  <option value="86400">每天（24h）</option>
                  <option value="604800">每周（7d）</option>
                  <option value="custom">自定义…</option>
                </select>
                <input
                  v-if="choiceFor(site) === 'custom'"
                  type="number"
                  min="3600"
                  max="2592000"
                  :value="customFor(site)"
                  placeholder="秒数（3600–2592000）"
                  :aria-label="`${site.label} 自定义间隔秒数`"
                  @input="customSeconds[site.main_url] = Number(($event.target as HTMLInputElement).value)"
                />
              </td>
              <td>
                <span class="ap-status" :data-tone="rowStatus(site).tone">{{ rowStatus(site).text }}</span>
              </td>
              <td>
                <button type="button" class="link" @click="onEdit(site.main_url)">编辑</button>
              </td>
            </tr>
          </tbody>
        </table>
        </div>
      </StateBlock>
    </section>

    <!-- ⑤ read-only widgets -->
    <section v-if="widgetsQuery.data.value" class="widgets">
      <div
        v-if="widgetsQuery.data.value.citation_alert"
        class="citation-alert"
        role="alert"
      >
        ⚠ Citation Share 偏低 —— 引用份额低于阈值（50%）。最近触发：{{ widgetsQuery.data.value.citation_alert.ts }}
      </div>

      <div class="plan-gap">
        <h2>⑤ Plan-Gap 周报</h2>
        <template v-if="widgetsQuery.data.value.plan_gap.status === 'ok'">
          <span class="badge">补链 seed 候选：{{ widgetsQuery.data.value.plan_gap.candidate_count }}</span>
          <span class="badge">涉及目标：{{ widgetsQuery.data.value.plan_gap.target_count }}</span>
          <span class="muted">触发时间：{{ widgetsQuery.data.value.plan_gap.triggered_at }}</span>
        </template>
        <p v-else-if="widgetsQuery.data.value.plan_gap.status === 'invalid'" class="muted">
          plan-gap 结果无法读取：{{ widgetsQuery.data.value.plan_gap.error }}
        </p>
        <p v-else class="muted">尚未执行 plan-gap（首次排程为下周日 02:00）。</p>
      </div>
    </section>
  </section>
</template>

<style scoped>
.sites {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.site-form,
.preview-box,
.autopilot,
.widgets {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
fieldset {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
legend {
  font-weight: var(--font-weight-semibold);
  padding: 0 0.4rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--text-lg);
}
label.checkbox {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}
input[type='text'],
input[type='number'],
textarea,
select {
  padding: var(--control-pad-y) var(--control-pad-x);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-raised);
  color: inherit;
  font: inherit;
}
.field-error {
  color: var(--danger);
  font-size: var(--text-sm);
}
.saved {
  color: var(--success);
}
.autofilled {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--primary);
  border-radius: var(--radius-md);
}
.form-actions {
  display: flex;
  gap: 0.5rem;
}
button.primary {
  padding: 0.45rem 1rem;
  cursor: pointer;
}
button.link {
  background: none;
  border: none;
  color: var(--primary);
  cursor: pointer;
}
.preview-row {
  display: flex;
  gap: 0.5rem;
}
.preview-row input {
  flex: 1;
}
.preview-out {
  background: var(--surface-raised);
  padding: 0.6rem;
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  max-height: 200px;
  overflow: auto;
}
.ap-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-base);
}
.ap-table th,
.ap-table td {
  text-align: left;
  padding: var(--control-pad-y) var(--control-pad-x);
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.truncate {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ap-status[data-tone='ok'] {
  color: var(--success);
}
.ap-status[data-tone='warn'] {
  color: var(--danger);
}
.citation-alert {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--warning);
  border-radius: var(--radius-md);
}
.plan-gap {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.badge {
  background: var(--surface-overlay);
  padding: 0.2rem 0.6rem;
  border-radius: var(--radius-pill);
  font-weight: var(--font-weight-semibold);
}
.muted {
  color: var(--text-secondary);
}
</style>
