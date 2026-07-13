<script setup lang="ts">
// Equity ledger — Plan P14 B1 (SPA migration).
import { computed, onMounted, ref } from 'vue'
import { fetchEquityLedger, triggerRecheck, type EquityRow } from '../../api/equityLedger'
import DataTable from '../../components/DataTable.vue'
import StatusBadge from '../../components/StatusBadge.vue'

const rows = ref<EquityRow[]>([])
const filteredRows = ref<EquityRow[]>([])
const error = ref<Error | null>(null)
const loading = ref(true)
const searchQuery = ref('')
const filterStatus = ref<'all' | 'needs-attention' | 'weak' | 'healthy'>('all')
const rechecking = ref(false)

const statusCounts = computed(() => {
  const total = rows.value.length
  const live = rows.value.filter(r => r.live && r.dofollow).length
  const weak = rows.value.filter(r => r.live && !r.dofollow).length
  const dead = rows.value.filter(r => !r.live).length
  return { total, live, weak, dead }
})

// Reflects the page's actual filter state (btn-group selection away from
// 'all', or a non-empty search query) -- drives the DataTable empty-text so
// a filtered-to-zero result reads distinctly from a genuinely empty dataset
// (reviewer finding, Task 8).
const hasActiveFilters = computed(
  () => filterStatus.value !== 'all' || searchQuery.value.trim() !== '',
)


const applyFilters = () => {
  let result = [...rows.value]
  if (filterStatus.value === 'needs-attention') {
    result = result.filter(r => !r.live || !r.dofollow)
  } else if (filterStatus.value === 'weak') {
    result = result.filter(r => r.live && !r.dofollow)
  } else if (filterStatus.value === 'healthy') {
    result = result.filter(r => r.live && r.dofollow)
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    result = result.filter(r =>
      r.target_url.toLowerCase().includes(q) ||
      r.main_domain.toLowerCase().includes(q) ||
      r.platform.toLowerCase().includes(q)
    )
  }
  filteredRows.value = result
}

const tableRows = computed(() =>
  filteredRows.value.map((r) => ({ ...r, id: `${r.target_url}|${r.platform}` })),
)

const load = async () => {
  loading.value = true
  error.value = null
  try {
    const data = await fetchEquityLedger()
    rows.value = data.rows ?? []
    applyFilters()
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
  } finally {
    loading.value = false
  }
}

const doRecheck = async () => {
  rechecking.value = true
  try {
    await triggerRecheck()
    await load()
  } catch {
    // Silent
  } finally {
    rechecking.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="equity">
    <header class="equity__head">
      <h1>权益总账</h1>
      <div class="equity__actions">
        <button class="btn btn-sm btn-outline-primary" @click="doRecheck" :disabled="rechecking">
          {{ rechecking ? '重新检查中...' : '批量重新检查' }}
        </button>
        <button class="btn btn-sm btn-outline-secondary" @click="load" :disabled="loading">
          刷新
        </button>
      </div>
    </header>

    <div v-if="!loading && !error && rows.length > 0" class="equity__stats d-flex gap-3 mb-2">
      <span>总计: <strong>{{ statusCounts.total }}</strong></span>
      <span class="text-success">存活: <strong>{{ statusCounts.live }}</strong></span>
      <span class="text-warning">弱: <strong>{{ statusCounts.weak }}</strong></span>
      <span class="text-danger">失效: <strong>{{ statusCounts.dead }}</strong></span>
    </div>

    <div v-if="!loading && !error && rows.length > 0" class="equity__filters d-flex gap-2 mb-2 flex-wrap">
      <div class="btn-group btn-group-sm">
        <button :class="['btn', filterStatus === 'all' ? 'btn-primary' : 'btn-outline-secondary']" @click="filterStatus = 'all'; applyFilters()">全部</button>
        <button :class="['btn', filterStatus === 'needs-attention' ? 'btn-warning' : 'btn-outline-secondary']" @click="filterStatus = 'needs-attention'; applyFilters()">需关注</button>
        <button :class="['btn', filterStatus === 'weak' ? 'btn-secondary' : 'btn-outline-secondary']" @click="filterStatus = 'weak'; applyFilters()">弱</button>
        <button :class="['btn', filterStatus === 'healthy' ? 'btn-success' : 'btn-outline-secondary']" @click="filterStatus = 'healthy'; applyFilters()">健康</button>
      </div>
      <input
        v-model="searchQuery"
        type="search"
        class="form-control form-control-sm"
        placeholder="搜索 URL / 平台..."
        style="max-width: 220px"
        @input="applyFilters"
      />
    </div>

    <DataTable
      :items="tableRows"
      :loading="loading"
      :error="error"
      :empty-text="hasActiveFilters ? '没有符合筛选条件的记录' : '暂无权益数据。'"
      caption="外链权益台账"
      @retry="load()"
    >
      <template #head>
        <th>目标 URL</th><th>主域</th><th>平台</th><th>Dofollow</th><th>存活</th>
        <th>相关度</th><th>首次发现</th><th>最后检查</th>
      </template>
      <template #row="{ row }">
        <td class="col-url"><code>{{ row.target_url }}</code></td>
        <td>{{ row.main_domain }}</td>
        <td>{{ row.platform }}</td>
        <td><StatusBadge :tone="row.dofollow ? 'success' : 'neutral'" :label="row.dofollow ? '是' : '否'" /></td>
        <td><StatusBadge :tone="row.live ? 'success' : 'danger'" :label="row.live ? '存活' : '失效'" /></td>
        <td class="col-num">{{ (row.relevance_score ?? 0).toFixed(2) }}</td>
        <td class="col-date">{{ row.first_seen ?? '—' }}</td>
        <td class="col-date">{{ row.last_checked ?? '—' }}</td>
      </template>
    </DataTable>
  </section>
</template>

<style scoped>
.equity {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.equity__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.equity__head h1 {
  margin: 0;
}
.equity__actions {
  display: flex;
  gap: 0.5rem;
}
.equity__stats {
  font-size: var(--text-lg);
}
</style>
