<script setup lang="ts">
// Publishing health dashboard — Plan 2026-07-02-001 U6.
//
// Versioned SPA sibling of the legacy /ce:health Jinja page — full panel
// parity (~20 panels), not a reduced summary. One GET /api/v1/health/summary
// call; every panel is fail-open (its own `degraded` flag + safe empty
// fallback), so one bad data source never blanks the rest of the dashboard
// (R3's "partial failure isolated" red line). `projection.degraded` (not
// `agg_degraded`, a pure belt-and-suspenders flag) is the primary signal for
// the aggregate health/projection block.
//
// No auto-polling: this data is expensive to aggregate (SQL scans, disk
// stats) and the legacy page itself has no client-side auto-refresh — a
// manual refresh button matches existing behavior rather than adding new
// continuous-polling cost the plan didn't ask for.
import { computed, reactive, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  circuitResetPlatform,
  fetchHealthSummary,
  fetchScorecardLinks,
  pausePlatform,
  recheckLink,
  reverifyPlatform,
  type HealthActionResult,
} from '../../api/health'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'
import { classifyError } from '../../lib/errors'

const QKEY = ['health-summary']
const qc = useQueryClient()
const notify = useNotificationsStore()
const { toastError } = useErrorToast()

const query = useQuery({ queryKey: QKEY, queryFn: fetchHealthSummary })

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

const summary = computed(() => query.data.value)
const panels = computed(() => summary.value?.panels)
const health = computed(() => summary.value?.health)
const projection = computed(() => summary.value?.projection)

function reportError(e: unknown): void {
  toastError(e)
}

// ── scorecard drill-down (fetch-on-expand) ──────────────────────────────
const expandedChannel = ref<string | null>(null)
const channelLinks = reactive<Record<string, Record<string, unknown>[]>>({})
const linksLoading = ref<string | null>(null)

async function toggleChannel(channel: string): Promise<void> {
  if (expandedChannel.value === channel) {
    expandedChannel.value = null
    return
  }
  expandedChannel.value = channel
  if (channel in channelLinks) return
  linksLoading.value = channel
  try {
    const r = await fetchScorecardLinks(channel)
    channelLinks[channel] = r.links
  } catch (e) {
    reportError(e)
  } finally {
    linksLoading.value = null
  }
}

const recheckBusy = ref<string | null>(null)
async function doRecheckLink(liveUrl: string): Promise<void> {
  if (recheckBusy.value) return
  recheckBusy.value = liveUrl
  try {
    const r = await recheckLink(liveUrl)
    if (r.ok) notify.push(`已重新核实：${r.verdict ?? ''}`, 'success')
    else notify.push('核实失败，请稍后重试', 'warning')
  } catch (e) {
    reportError(e)
  } finally {
    recheckBusy.value = null
  }
}

// ── platform actions (pause/resume, reverify, circuit-reset) ───────────
const actionBusy = ref<string | null>(null)

/** Run a platform action, write the result straight into the cache (no
 * refetch) -- mirrors the History/Drafts mutation pattern. */
async function runAction(
  key: string,
  fn: () => Promise<HealthActionResult>,
  onOk: (r: HealthActionResult) => string | void,
): Promise<void> {
  if (actionBusy.value) return
  actionBusy.value = key
  try {
    const r = await fn()
    if (!r.ok) {
      notify.push(r.reason ? `操作未完成：${r.reason}` : '操作未完成', 'warning')
      return
    }
    const msg = onOk(r)
    if (msg) notify.push(msg, 'success')
    query.refetch()
  } catch (e) {
    reportError(e)
  } finally {
    actionBusy.value = null
  }
}

const doPause = (platform: string, paused: boolean) =>
  runAction(`pause:${platform}`, () => pausePlatform(platform, paused), (r) =>
    r.paused ? `已暂停 ${platform}` : `已恢复 ${platform}`,
  )
const doReverify = (platform: string) =>
  runAction(`reverify:${platform}`, () => reverifyPlatform(platform), (r) =>
    r.ready ? `${platform} 校验通过` : `${platform} 校验未通过：${r.reason ?? ''}`,
  )
const doCircuitReset = (platform: string) =>
  runAction(`circuit:${platform}`, () => circuitResetPlatform(platform), () => `已重置 ${platform} 熔断器`)

// ── generic panel-table rendering for the secondary/telemetry panels ────
// These panels vary widely in shape (query-row lists, scalar aggregates) and
// are read-only telemetry the operator scans rather than acts on -- a single
// generic renderer (columns derived from object keys) covers all of them
// without ~15 bespoke bespoke widgets for data this secondary.
function asRows(data: unknown): Record<string, unknown>[] {
  if (Array.isArray(data)) return data as Record<string, unknown>[]
  if (data && typeof data === 'object' && Object.keys(data).length) return [data as Record<string, unknown>]
  return []
}
function columnsOf(rows: Record<string, unknown>[]): string[] {
  const seen = new Set<string>()
  for (const row of rows) for (const k of Object.keys(row)) seen.add(k)
  return [...seen]
}
function cell(value: unknown): string {
  if (value == null) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const secondaryPanels = computed(() => {
  const p = panels.value
  if (!p) return []
  return [
    { key: 'geo_panel', label: 'GEO 引用占比', panel: p.geo_panel, data: (p.geo_panel.data as { targets?: unknown[] })?.targets },
    { key: 'decay_alerts', label: '衰减告警（14 天）', panel: p.decay_alerts },
    { key: 'gsc_indexation', label: 'GSC 收录状态', panel: p.gsc_indexation },
    { key: 'gsc_ranking', label: 'GSC 排名趋势', panel: p.gsc_ranking },
    { key: 'publish_index_latency', label: '发布→收录延迟', panel: p.publish_index_latency },
    { key: 'index_rate_by_channel', label: '各渠道收录率', panel: p.index_rate_by_channel },
    { key: 'impression_analysis', label: '曝光分析', panel: p.impression_analysis },
    { key: 'ranking_lift_analysis', label: '排名提升分析', panel: p.ranking_lift_analysis },
    { key: 'referral_conversion', label: '推荐转化', panel: p.referral_conversion },
    { key: 'cost_metrics', label: '成本指标', panel: p.cost_metrics },
    { key: 'decisions_by_platform', label: '各平台决策分布', panel: p.decisions_by_platform },
    { key: 'pipeline_summary', label: '流水线摘要（24h/7d/30d）', panel: p.pipeline_summary },
    { key: 'reconciliation_gaps', label: '对账缺口', panel: p.reconciliation_gaps },
    { key: 'recheck_decay', label: '存活衰减计数', panel: p.recheck_decay },
    { key: 'autopilot_alerts', label: '自动巡航告警', panel: p.autopilot_alerts },
    { key: 'weights_snapshot', label: '权重快照', panel: p.weights_snapshot },
  ].map((entry) => ({ ...entry, rows: asRows(entry.data ?? entry.panel.data) }))
})
</script>

<template>
  <section class="health">
    <header class="health__head">
      <h1>发布健康看板</h1>
      <button type="button" class="btn-refresh" :disabled="query.isFetching.value" @click="query.refetch()">
        刷新
      </button>
    </header>

    <div v-if="projection?.degraded" class="alert alert-warning" role="alert">
      ⚠ 数据可能不完整（{{ projection.degraded_reason ?? '未知原因' }}）
    </div>
    <div v-if="projection?.gap" class="alert alert-warning" role="alert">
      ⚠ 存在未处理的数据缺口（{{ projection.gap_reason ?? '' }}）
    </div>

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      :is-fetching="query.isFetching.value"
      empty-text="暂无健康数据"
      @retry="query.refetch()"
    >
      <template v-if="health && panels">
        <!-- Hero: success rate -->
        <div class="health__hero">
          <div class="stat">
            <span class="stat__label">窗口内成功率（{{ health.window_days }} 天）</span>
            <span class="stat__value">
              {{ health.success.pct != null ? `${(health.success.pct * 100).toFixed(1)}%` : '暂无数据' }}
            </span>
            <span class="muted">{{ health.success.confirmed }} / {{ health.success.targets }}</span>
          </div>
          <div v-if="panels.publish_metrics.data.success_rate" class="stat">
            <span class="stat__label">发布成功率（B2）</span>
            <span class="stat__value">
              {{ panels.publish_metrics.data.success_rate.pct != null
                ? `${(panels.publish_metrics.data.success_rate.pct * 100).toFixed(1)}%` : '暂无数据' }}
            </span>
          </div>
          <div v-if="panels.storage_health.data.events_db_mb != null" class="stat">
            <span class="stat__label">events.db</span>
            <span class="stat__value" :class="{ warn: panels.storage_health.data.events_db_warn }">
              {{ panels.storage_health.data.events_db_mb }} MB
            </span>
            <span class="muted">{{ panels.storage_health.data.events_rows ?? 0 }} 行</span>
          </div>
        </div>

        <!-- Channel scorecard -->
        <section class="health__section">
          <h2>渠道价值记分卡 <span v-if="panels.channel_scorecard.degraded" class="degraded-tag">数据不可用</span></h2>
          <div class="data-table-wrap" v-if="panels.channel_scorecard.data.length">
            <table class="data-table">
              <thead>
                <tr><th>渠道</th><th></th></tr>
              </thead>
              <tbody>
                <template v-for="row in panels.channel_scorecard.data" :key="String(row.channel)">
                  <tr>
                    <td>{{ row.channel }}</td>
                    <td>
                      <button type="button" @click="toggleChannel(String(row.channel))">
                        {{ expandedChannel === row.channel ? '收起' : '查看链接' }}
                      </button>
                    </td>
                  </tr>
                  <tr v-if="expandedChannel === row.channel">
                    <td colspan="2">
                      <p v-if="linksLoading === row.channel" class="muted">加载中…</p>
                      <ul v-else-if="channelLinks[String(row.channel)]?.length" class="link-list">
                        <li v-for="(link, i) in channelLinks[String(row.channel)]" :key="i">
                          <code>{{ link.live_url ?? link.url }}</code>
                          <button
                            type="button"
                            :disabled="recheckBusy === (link.live_url ?? link.url)"
                            @click="doRecheckLink(String(link.live_url ?? link.url))"
                          >
                            重核
                          </button>
                        </li>
                      </ul>
                      <p v-else class="muted">此渠道暂无链接</p>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">暂无渠道记分卡数据</p>
        </section>

        <!-- Canary + forward-path -->
        <div class="health__two-col">
          <section class="health__section">
            <h2>常青探针 <span v-if="panels.canary.degraded" class="degraded-tag">数据不可用</span></h2>
            <div class="data-table-wrap" v-if="panels.canary.data.length">
              <table class="data-table">
                <thead><tr><th>平台</th><th>状态</th><th>连续失败</th><th>已隔离</th></tr></thead>
                <tbody>
                  <tr v-for="row in panels.canary.data" :key="row.platform">
                    <td>{{ row.platform }}</td>
                    <td>{{ row.status ?? '—' }}</td>
                    <td>{{ row.consecutive_failures }}</td>
                    <td>{{ row.quarantined ? '是' : '否' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted">暂无数据</p>
          </section>

          <section class="health__section">
            <h2>发布路径探针 <span v-if="panels.forward_path.degraded" class="degraded-tag">数据不可用</span></h2>
            <div class="data-table-wrap" v-if="panels.forward_path.data.length">
              <table class="data-table">
                <thead><tr><th>平台</th><th>状态</th><th>连续失败</th><th>降级</th></tr></thead>
                <tbody>
                  <tr v-for="row in panels.forward_path.data" :key="row.platform">
                    <td>{{ row.platform }}</td>
                    <td>{{ row.status ?? '—' }}</td>
                    <td>{{ row.consecutive_failures }}</td>
                    <td>{{ row.degraded ? '是' : '否' }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted">暂无数据</p>
          </section>
        </div>

        <!-- Platform health + actions -->
        <section class="health__section">
          <h2>平台状态与操作 <span v-if="panels.platform_health.degraded" class="degraded-tag">数据不可用</span></h2>
          <div class="data-table-wrap" v-if="Object.keys(panels.platform_health.data).length">
            <table class="data-table">
              <thead>
                <tr>
                  <th>平台</th><th>暂停</th><th>连续失败</th><th>熔断</th><th>最近失败</th><th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(rec, platform) in panels.platform_health.data" :key="platform">
                  <td>{{ platform }}</td>
                  <td>{{ rec.paused ? '是' : '否' }}</td>
                  <td>{{ rec.consecutive_failures }}</td>
                  <td>{{ rec.circuit_tripped ? '是' : '否' }}</td>
                  <td class="muted">{{ rec.last_failure_at ?? '—' }}</td>
                  <td class="row-actions">
                    <button
                      type="button"
                      :disabled="actionBusy === `pause:${platform}`"
                      @click="doPause(String(platform), !rec.paused)"
                    >
                      {{ rec.paused ? '恢复' : '暂停' }}
                    </button>
                    <button
                      type="button"
                      :disabled="actionBusy === `reverify:${platform}`"
                      @click="doReverify(String(platform))"
                    >
                      重新校验
                    </button>
                    <button
                      type="button"
                      :disabled="!rec.circuit_tripped || actionBusy === `circuit:${platform}`"
                      @click="doCircuitReset(String(platform))"
                    >
                      重置熔断器
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">暂无平台数据</p>
        </section>

        <!-- Secondary telemetry panels (generic rendering) -->
        <details class="health__more">
          <summary>更多指标（{{ secondaryPanels.length }}）</summary>
          <section v-for="entry in secondaryPanels" :key="entry.key" class="health__section">
            <h3>{{ entry.label }} <span v-if="entry.panel.degraded" class="degraded-tag">数据不可用</span></h3>
            <div class="data-table-wrap" v-if="entry.rows.length">
              <table class="data-table">
                <thead>
                  <tr><th v-for="col in columnsOf(entry.rows)" :key="col">{{ col }}</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(row, i) in entry.rows" :key="i">
                    <td v-for="col in columnsOf(entry.rows)" :key="col">{{ cell(row[col]) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else class="muted">暂无数据</p>
          </section>
        </details>
      </template>
    </StateBlock>
  </section>
</template>

<style scoped>
.health {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.health__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.health__hero {
  display: flex;
  gap: 1.5rem;
  flex-wrap: wrap;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  padding: 0.5rem 1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  min-width: 10rem;
}
.stat__label {
  font-size: 0.8rem;
  color: var(--text-secondary);
}
.stat__value {
  font-size: 1.4rem;
  font-weight: 600;
}
.stat__value.warn {
  color: var(--danger);
}
.health__section h2,
.health__section h3 {
  margin: 0 0 0.5rem;
}
.health__two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}
@media (max-width: 60rem) {
  .health__two-col {
    grid-template-columns: 1fr;
  }
}
.degraded-tag {
  font-size: 0.75rem;
  color: var(--danger);
  font-weight: 400;
}
.row-actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}
.link-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.link-list li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.health__more summary {
  cursor: pointer;
  font-weight: 600;
  margin-bottom: 0.75rem;
}
.health__more .health__section {
  margin-top: 1rem;
}
</style>
