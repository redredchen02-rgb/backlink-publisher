<script setup lang="ts">
// PR opportunity queue — Plan P12 A1 (SPA Phase 3 migration).
//
// Plan 2026-07-02-001 U15 B1: `pr_queue` is one of the blueprints
// LITE_HIDDEN_BLUEPRINTS gates server-side (webui_app/__init__.py's
// `_lite_surface_gate`) — under LITE edition every call to `/api/pr-queue`
// 404s, unconditionally and permanently. That 404 is deliberately generic
// ("uniform with any unmatched path, so it leaks no hidden-route existence" —
// see the gate's own docstring), so it must NOT be made distinguishable from
// a real 404 at the HTTP layer. Instead this page checks the same
// `/app-config` `lite_edition` flag TopBar.vue already reads, and skips the
// doomed request entirely — showing an accurate "unavailable in this
// edition" empty state instead of classifyError's generic "出错了" +
// a retry button that could never succeed.
import { computed, onMounted, ref } from 'vue'
import { fetchPrQueue, updatePrStatus, type PrItem } from '../../api/prQueue'
import { getJson } from '../../api/client'
import StateBlock from '../../components/StateBlock.vue'

interface AppConfig {
  lite_edition: boolean
}

const items = ref<PrItem[]>([])
const error = ref<Error | null>(null)
const loading = ref(true)
const updating = ref<Set<string>>(new Set())
const liteUnavailable = ref(false)

const STATUS_COLORS: Record<string, string> = {
  pending: 'yellow',
  draft: 'blue',
  sent: 'purple',
  won: 'green',
  lost: 'red',
  skipped: 'gray',
}

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (liteUnavailable.value) return 'empty'
  if (items.value.length === 0) return 'empty'
  return 'ready'
})

const emptyText = computed(() =>
  liteUnavailable.value
    ? 'PR 机会队列在当前版本（LITE）中未开放。'
    : '暂无 PR 机会。通过 pr-opportunities ingest 导入 HARO/SOS/HaB2BW 摘要。',
)

const load = async () => {
  loading.value = true
  error.value = null
  liteUnavailable.value = false
  try {
    // The LITE check is a best-effort optimization, not a hard gate: a
    // transient /app-config failure (network hiccup, timeout) must not
    // block the actual queue fetch in full edition, where /api/pr-queue
    // itself would have succeeded fine. Fail open to "not LITE" on error —
    // code review found the original unconditional single try/catch here
    // coupled pr-queue availability to an unrelated endpoint's health.
    let isLite = false
    try {
      const config = await getJson<AppConfig>('/app-config')
      isLite = config.lite_edition === true
    } catch {
      // Best-effort only — fall through to the real fetch below.
    }
    if (isLite) {
      liteUnavailable.value = true
      items.value = []
      return
    }
    items.value = await fetchPrQueue()
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
  } finally {
    loading.value = false
  }
}

const markStatus = async (id: string, status: string) => {
  if (updating.value.has(id)) return
  updating.value = new Set(updating.value).add(id)
  try {
    await updatePrStatus(id, status)
    await load()
  } catch {
    // Error is surfaced by load()
    await load()
  } finally {
    const next = new Set(updating.value)
    next.delete(id)
    updating.value = next
  }
}

onMounted(load)
</script>

<template>
  <section class="pr-queue">
    <header class="pr-queue__head">
      <h1>PR 机会队列</h1>
      <button class="btn btn-sm btn-outline-secondary" @click="load" :disabled="loading">
        刷新
      </button>
    </header>

    <StateBlock
      :state="blockState"
      :error="error"
      :empty-text="emptyText"
      @retry="load"
    >
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>状态</th>
              <th>相关度</th>
              <th>标题</th>
              <th>摘要</th>
              <th>来源</th>
              <th>截止</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.id" :data-id="item.id">
              <td class="col-status">
                <span
                  class="badge"
                  :class="`bg-${STATUS_COLORS[item.status] ?? 'secondary'}`"
                >{{ item.status }}</span>
              </td>
              <td class="col-num text-center">
                <span class="fw-semibold">{{ Math.round(item.relevance_score ?? 0) }}</span>
              </td>
              <td class="pr-queue__headline-cell">
                <span class="fw-semibold">{{ item.headline ?? '—' }}</span>
              </td>
              <td class="pr-queue__summary-cell text-muted">
                {{ (item.summary ?? '').slice(0, 120) }}{{ (item.summary ?? '').length > 120 ? '…' : '' }}
              </td>
              <td><span class="badge bg-secondary">{{ item.source ?? '—' }}</span></td>
              <td class="col-date text-muted pr-queue__deadline-cell">{{ item.deadline ?? '—' }}</td>
              <td>
                <div class="btn-group btn-group-sm" role="group">
                  <button
                    class="btn btn-outline-success"
                    :disabled="updating.has(item.id)"
                    title="标记为已获得"
                    aria-label="标记为已获得"
                    @click="markStatus(item.id, 'won')"
                  >✓</button>
                  <button
                    class="btn btn-outline-secondary"
                    :disabled="updating.has(item.id)"
                    title="跳过"
                    aria-label="跳过此机会"
                    @click="markStatus(item.id, 'skipped')"
                  >✕</button>
                </div>
                <span v-if="updating.has(item.id)" class="ms-1 spinner-border spinner-border-sm" role="status" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
.pr-queue {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.pr-queue__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.pr-queue__head h1 {
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.pr-queue__headline-cell {
  max-width: 280px;
  white-space: normal;
}
.pr-queue__summary-cell {
  max-width: 320px;
  white-space: normal;
  font-size: 0.875rem;
}
.pr-queue__deadline-cell {
  font-size: 0.8rem;
}
</style>
