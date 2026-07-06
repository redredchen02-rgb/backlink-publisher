<script setup lang="ts">
// Keep-alive status screen — Plan P15 A1 (SPA migration).
// State machine: S0 (scorecard) → S1 (recheck) → S2 (healthy) → S3 (gap select) → S4 (confirm) → S5 (republish progress) → S6/S7 (result)
//
// Plan 2026-07-02-001 U5: both job-status polls (recheck, republish) migrated
// to usePolledQuery, fixing the un-backed-off fixed-2s setTimeout retry loop
// this unit's plan named directly. Each poll is gated on its job id being set
// (usePolledQuery's `enabled`) rather than an explicit startPolling() call --
// vue-query auto-fires the first fetch the moment `enabled` flips true, and
// stops entirely (no setTimeout chain to clear on unmount) once `isTerminal`
// sees a completed/cancelled/error status. The side effects that used to live
// inline in each hand-rolled poll() callback (state-machine transition, flash
// message, reloading the scorecard) now live in a `watch` on the query's data.
import { computed, onMounted, ref, watch } from 'vue'
import {
  fetchSummary, startRecheck, pollRecheck, cancelRecheck,
  getRepublishToken, executeRepublish, pollRepublish,
  fetchCycleStatus, resetExhausted,
  type KeepAliveSummary, type KeepAliveGap, type RepublishResult,
} from '../../api/keepAlive'
import StateBlock from '../../components/StateBlock.vue'
import { usePolledQuery } from '../../composables/usePolledQuery'

const RECHECK_TERMINAL = new Set(['completed', 'done', 'cancelled', 'error'])
const REPUBLISH_TERMINAL = new Set(['completed', 'done', 'error'])

// ── State machine ──────────────────────────────────────────────────────────
type PageState = 'loading' | 'error' | 'empty' | 'stale' | 'ready'
type ActionState = 'idle' | 'rechecking' | 'healthy' | 'selecting' | 'confirming' | 'publishing' | 'result'

const pageState = ref<PageState>('loading')
const actionState = ref<ActionState>('idle')
const error = ref<Error | null>(null)
const summary = ref<KeepAliveSummary | null>(null)
const flashMessage = ref('')
// Cycle status is a secondary/non-critical panel fetched alongside the
// scorecard. Its failure is tracked independently (see `load()`) so a
// transient error there cannot blank the already-loaded scorecard.
const cycleStatusError = ref(false)

// Recheck state
const recheckJobId = ref('')
const recheckProgress = ref(0)
const recheckTotal = ref(0)
const recheckMessage = ref('')

// Republish state
const selectedGaps = ref<Set<string>>(new Set())
const republishToken = ref('')
const republishJobId = ref('')
const republishStage = ref('')
const republishMessage = ref('')

// Cycle status
const cycleStatus = ref<{ running: boolean; stage?: string; status?: string } | null>(null)

// Computed
const scorecardTargets = computed(() => summary.value?.targets ?? [])
const gaps = computed(() => summary.value?.gaps ?? [])
const aliveCount = computed(() => summary.value?.alive_count ?? 0)
const strippedCount = computed(() => summary.value?.stripped_count ?? 0)
const unknownCount = computed(() => summary.value?.unknown_count ?? 0)
const hasGaps = computed(() => gaps.value.length > 0)
const allSelected = computed(() => selectedGaps.value.size === gaps.value.length)

const stripRateClass = (rate: number): string => {
  if (rate >= 0.5) return 'text-danger'
  if (rate >= 0.25) return 'text-warning'
  return ''
}

// ── Load initial data ──────────────────────────────────────────────────────
const load = async () => {
  pageState.value = 'loading'
  error.value = null
  try {
    summary.value = await fetchSummary()
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
    pageState.value = 'error'
    return
  }
  if (summary.value.is_empty) {
    pageState.value = 'empty'
  } else if (summary.value.stale) {
    pageState.value = 'stale'
  } else {
    pageState.value = 'ready'
  }
  // Isolated on purpose (own try/catch, not folded into the summary fetch
  // above): a cycle-status failure must not blank the scorecard that already
  // loaded fine (R3 action 6/7 — partial failure must not blank sibling data).
  try {
    cycleStatus.value = await fetchCycleStatus()
    cycleStatusError.value = false
  } catch {
    cycleStatus.value = null
    cycleStatusError.value = true
  }
}

// ── S1: Recheck ────────────────────────────────────────────────────────────
const doRecheck = async () => {
  actionState.value = 'rechecking'
  try {
    const result = await startRecheck()
    // Setting a truthy job id flips usePolledQuery's `enabled` -- vue-query
    // fires the first poll on its own, no explicit "start" call needed.
    recheckJobId.value = result.job_id ?? ''
  } catch (e) {
    flashMessage.value = `启动巡检失败: ${e instanceof Error ? e.message : String(e)}`
    actionState.value = 'idle'
  }
}

const recheckQuery = usePolledQuery({
  queryKey: computed(() => ['keepalive-recheck', recheckJobId.value]),
  queryFn: () => pollRecheck(recheckJobId.value),
  intervalMs: 2000,
  isTerminal: (data) => !!data && RECHECK_TERMINAL.has(data.status),
  enabled: computed(() => !!recheckJobId.value),
})

watch(recheckQuery.data, (status) => {
  if (!status) return
  recheckProgress.value = status.progress ?? 0
  recheckTotal.value = status.total ?? 0
  recheckMessage.value = status.message ?? ''
  if (status.status === 'completed' || status.status === 'done') {
    actionState.value = 'idle'
    recheckJobId.value = ''
    load()
  } else if (status.status === 'cancelled' || status.status === 'error') {
    actionState.value = 'idle'
    flashMessage.value = status.message ?? '巡检已取消'
    recheckJobId.value = ''
    load()
  }
})

const doCancelRecheck = async () => {
  if (!recheckJobId.value) return
  try {
    await cancelRecheck(recheckJobId.value)
    flashMessage.value = '巡检已取消'
    actionState.value = 'idle'
  } catch { /* silent */ }
}

// ── S3-S7: Republish ───────────────────────────────────────────────────────
const toggleGap = (key: string) => {
  const next = new Set(selectedGaps.value)
  if (next.has(key)) next.delete(key); else next.add(key)
  selectedGaps.value = next
}

const toggleAllGaps = () => {
  if (allSelected.value) {
    selectedGaps.value = new Set()
  } else {
    selectedGaps.value = new Set(gaps.value.map(g => `${g.target_url}:${g.platform}`))
  }
}

const gapKey = (g: KeepAliveGap): string => `${g.target_url}:${g.platform}`

const startConfirm = async () => {
  if (!hasGaps.value) return
  try {
    const result = await getRepublishToken()
    if (!result.ok) {
      flashMessage.value = result.error ?? '获取确认令牌失败'
      return
    }
    republishToken.value = (result as RepublishResult & { token: string }).token
    actionState.value = 'confirming'
  } catch (e) {
    flashMessage.value = `获取令牌失败: ${e instanceof Error ? e.message : String(e)}`
  }
}

const cancelConfirm = () => {
  actionState.value = selectingGaps() ? 'selecting' : 'idle'
}

const selectingGaps = () => hasGaps.value && actionState.value !== 'confirming'

const doRepublish = async () => {
  if (!republishToken.value || selectedGaps.value.size === 0) return
  actionState.value = 'publishing'
  const gapKeys = Array.from(selectedGaps.value).map(k => {
    const [target_url, platform] = k.split(':')
    return JSON.stringify({ target_url, platform })
  })
  try {
    const result = await executeRepublish(republishToken.value, gapKeys)
    if (!result.ok) {
      flashMessage.value = result.message ?? '发布失败'
      actionState.value = 'idle'
      return
    }
    // Setting a truthy job id flips usePolledQuery's `enabled` -- vue-query
    // fires the first poll on its own, no explicit "start" call needed.
    republishJobId.value = result.job_id ?? ''
  } catch (e) {
    flashMessage.value = `发布失败: ${e instanceof Error ? e.message : String(e)}`
    actionState.value = 'idle'
  }
}

const republishQuery = usePolledQuery({
  queryKey: computed(() => ['keepalive-republish', republishJobId.value]),
  queryFn: () => pollRepublish(republishJobId.value),
  intervalMs: 2000,
  isTerminal: (data) => !!data && REPUBLISH_TERMINAL.has(data.status),
  enabled: computed(() => !!republishJobId.value),
})

watch(republishQuery.data, (status) => {
  if (!status) return
  republishStage.value = status.status
  republishMessage.value = status.message ?? ''
  if (status.status === 'completed' || status.status === 'done') {
    actionState.value = 'result'
    republishJobId.value = ''
    load()
  } else if (status.status === 'error') {
    flashMessage.value = status.message ?? '发布过程出错'
    actionState.value = 'idle'
    republishJobId.value = ''
  }
})

const finishRepublish = () => {
  actionState.value = 'idle'
  selectedGaps.value = new Set()
  load()
}

// ── Reset exhausted ────────────────────────────────────────────────────────
const doResetExhausted = async () => {
  try {
    await resetExhausted()
    flashMessage.value = '已重置重试计数'
    await load()
  } catch { /* silent */ }
}

// ── Cycle Status ───────────────────────────────────────────────────────────
const refreshCycleStatus = async () => {
  try {
    cycleStatus.value = await fetchCycleStatus()
    cycleStatusError.value = false
  } catch {
    cycleStatusError.value = true
  }
}

// ── Lifecycle ──────────────────────────────────────────────────────────────
onMounted(load)
</script>

<template>
  <section class="ka">
    <header class="ka__head">
      <h1>保活看板</h1>
      <div class="ka__actions">
        <button v-if="actionState === 'idle'" class="btn btn-sm btn-primary" @click="doRecheck">巡检</button>
        <button class="btn btn-sm btn-outline-secondary" @click="load" :disabled="pageState === 'loading'">刷新</button>
      </div>
    </header>

    <!-- Flash message -->
    <div v-if="flashMessage" class="alert alert-info alert-dismissible">
      {{ flashMessage }}
      <button type="button" class="btn-close" @click="flashMessage = ''" />
    </div>

    <!-- S0: Stale banner -->
    <div v-if="pageState === 'stale'" class="alert alert-warning">
      数据可能过时（{{ summary?.stale_days ?? 0 }} 天未更新）。请运行巡检以获取最新数据。
    </div>

    <!-- S1: Recheck progress -->
    <div v-if="actionState === 'rechecking'" class="ka__progress card p-3 mb-3">
      <h5>巡检中...</h5>
      <div class="progress mb-2" v-if="recheckTotal > 0">
        <div class="progress-bar progress-bar-striped progress-bar-animated" :style="{ width: (recheckTotal > 0 ? (recheckProgress / recheckTotal * 100) : 0) + '%' }" />
      </div>
      <p class="text-muted small">{{ recheckMessage || `${recheckProgress}/${recheckTotal}` }}</p>
      <button class="btn btn-sm btn-outline-danger" @click="doCancelRecheck">取消</button>
    </div>

    <!-- S2: Healthy -->
    <div v-if="actionState === 'healthy'" class="alert alert-success">
      一切正常 — 发布链路稳定，无需重新发布。
    </div>

    <StateBlock
      :state="pageState === 'loading' ? 'loading' : pageState === 'error' ? 'error' : pageState === 'empty' ? 'empty' : 'ready'"
      :error="error"
      empty-text="暂无数据。先发布一些文章，然后运行巡检。"
      @retry="load"
    >
      <!-- S0: Scorecard -->
      <div class="ka__scorecard">
        <div class="ka__stats d-flex gap-3 mb-2 flex-wrap">
          <span class="badge bg-success">存活 {{ aliveCount }}</span>
          <span class="badge bg-danger">失效 {{ strippedCount }}</span>
          <span class="badge bg-secondary">未知 {{ unknownCount }}</span>
        </div>

        <div class="data-table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>目标 URL</th>
                <th>平台</th>
                <th>存活</th>
                <th>失效</th>
                <th>衰减</th>
                <th>检查失败</th>
                <th>失效比率</th>
                <th>趋势</th>
                <th>最后验证</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in scorecardTargets" :key="t.target_url" :class="t.needs_attention ? 'needs-attention' : ''">
                <td class="col-url"><code class="text-truncate d-inline-block" style="max-width:180px">{{ t.target_url }}</code></td>
                <td>{{ t.platforms }}</td>
                <td class="col-num text-center">{{ t.live_dofollow }}</td>
                <td class="col-num text-center text-danger">{{ t.stripped }}</td>
                <td class="col-num text-center">{{ t.decayed }}</td>
                <td class="col-num text-center">{{ t.check_failed }}</td>
                <td :class="['col-num text-center', stripRateClass(t.strip_rate)]">{{ (t.strip_rate * 100).toFixed(0) }}%</td>
                <td><span :class="t.trend === 'up' ? 'text-success' : t.trend === 'down' ? 'text-danger' : ''">{{ t.trend }}</span></td>
                <td class="col-date text-muted small">{{ t.last_verified ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- S0: Cycle status — a failed fetch here must not blank the scorecard
           above (which already loaded fine); show its own persistent error
           indicator instead (R3 action 6/7). -->
      <div v-if="cycleStatusError" class="ka__cycle-error alert alert-warning mt-3" role="alert">
        ⚠ 自动保活周期状态加载失败，不影响上方数据。
        <button type="button" class="btn btn-sm btn-outline-secondary ms-2" @click="refreshCycleStatus">重试</button>
      </div>
      <div v-else-if="cycleStatus" class="ka__cycle mt-3">
        <details>
          <summary class="text-muted" style="cursor:pointer">
            自动保活周期
            <span v-if="cycleStatus.running" class="badge bg-primary ms-1">运行中</span>
          </summary>
          <div class="mt-2 small">
            <p>状态: {{ cycleStatus.status ?? '—' }}</p>
            <p>阶段: {{ cycleStatus.stage ?? '—' }}</p>
            <button class="btn btn-sm btn-outline-secondary" @click="refreshCycleStatus">刷新状态</button>
          </div>
        </details>
      </div>

      <!-- S3: Gap selection + S4: Confirm + S5: Publish -->
      <div v-if="hasGaps && actionState !== 'rechecking'" class="ka__republish mt-3">
        <!-- S3: Gap selection -->
        <div v-if="actionState === 'idle' || actionState === 'selecting'">
          <div class="d-flex align-items-center gap-2 mb-2">
            <h5 class="m-0">需要重新发布的链接</h5>
            <button class="btn btn-sm btn-outline-primary" @click="startConfirm" :disabled="selectedGaps.size === 0">
              重新发布 ({{ selectedGaps.size }})
            </button>
            <button class="btn btn-sm btn-outline-danger" @click="doResetExhausted">重置重试计数</button>
          </div>
          <div class="form-check mb-1">
            <input class="form-check-input" type="checkbox" :checked="allSelected" @change="toggleAllGaps" id="selectAll" />
            <label class="form-check-label" for="selectAll">全选</label>
          </div>
          <div v-for="g in gaps" :key="gapKey(g)" class="form-check">
            <input class="form-check-input" type="checkbox" :checked="selectedGaps.has(gapKey(g))" @change="toggleGap(gapKey(g))" :id="gapKey(g)" />
            <label class="form-check-label" :for="gapKey(g)">
              <code>{{ g.target_url }}</code> <span class="badge bg-secondary">{{ g.platform }}</span>
              <span class="text-muted small ms-2">失效于 {{ g.stripped_ts }}</span>
            </label>
          </div>
        </div>

        <!-- S4: Confirm modal overlay -->
        <div v-if="actionState === 'confirming'" class="ka__confirm-overlay">
          <div class="ka__confirm-modal">
            <h5>确认重新发布</h5>
            <p class="text-danger">此操作将重新发布以下链接，不可撤销。</p>
            <ul>
              <li v-for="k of Array.from(selectedGaps)" :key="k">
                <code>{{ k.split(':')[0] }}</code> — {{ k.split(':')[1] }}
              </li>
            </ul>
            <div class="d-flex gap-2">
              <button class="btn btn-danger" @click="doRepublish">确认重新发布</button>
              <button class="btn btn-outline-secondary" @click="cancelConfirm">取消</button>
            </div>
          </div>
        </div>

        <!-- S5: Republish progress -->
        <div v-if="actionState === 'publishing'" class="ka__progress card p-3">
          <h5>重新发布中...</h5>
          <div class="spinner-border text-primary mb-2" role="status" />
          <p class="text-muted small">{{ republishMessage || republishStage }}</p>
        </div>

        <!-- S6/S7: Result -->
        <div v-if="actionState === 'result'" class="alert alert-success">
          重新发布已完成！
          <button class="btn btn-sm btn-outline-primary ms-2" @click="finishRepublish">完成</button>
        </div>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
.ka {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.ka__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.ka__head h1 { margin: 0; }
.ka__actions { display: flex; gap: 0.5rem; }
.ka__confirm-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 1050;
}
.ka__confirm-modal {
  background: var(--surface-raised);
  border-radius: 12px; padding: 1.5rem; max-width: 500px; width: 90%;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
/* "Needs attention" row highlight — Bootstrap's table-warning only paints via
   a selector requiring an ancestor .table class, which the .data-table
   migration removed from this page's <table>. Use the console's own token
   instead of depending on Bootstrap's table-variant mechanism. */
.data-table tr.needs-attention td {
  background: var(--warning-soft);
}
</style>
