<script setup lang="ts">
// Equity ledger — Plan P14 B1 (SPA migration).
import { computed, onMounted, ref } from 'vue'
import { fetchEquityLedger, triggerRecheck, type EquityRow } from '../../api/equityLedger'
import StateBlock from '../../components/StateBlock.vue'

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

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (rows.value.length === 0) return 'empty'
  return 'ready'
})

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

    <div v-if="blockState === 'ready'" class="equity__stats d-flex gap-3 mb-2">
      <span>总计: <strong>{{ statusCounts.total }}</strong></span>
      <span class="text-success">存活: <strong>{{ statusCounts.live }}</strong></span>
      <span class="text-warning">弱: <strong>{{ statusCounts.weak }}</strong></span>
      <span class="text-danger">失效: <strong>{{ statusCounts.dead }}</strong></span>
    </div>

    <div v-if="blockState === 'ready'" class="equity__filters d-flex gap-2 mb-2 flex-wrap">
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

    <StateBlock
      :state="blockState"
      :error="error"
      empty-text="暂无权益数据。"
      @retry="load"
    >
      <div class="table-wrap">
        <table class="table table-sm table-hover align-middle mb-0">
          <thead class="table-light">
            <tr>
              <th>目标 URL</th>
              <th>主域</th>
              <th>平台</th>
              <th>Dofollow</th>
              <th>存活</th>
              <th>相关度</th>
              <th>首次发现</th>
              <th>最后检查</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredRows" :key="row.target_url + row.platform">
              <td><code class="text-truncate d-inline-block" style="max-width: 200px">{{ row.target_url }}</code></td>
              <td>{{ row.main_domain }}</td>
              <td>{{ row.platform }}</td>
              <td>
                <span :class="['badge', row.dofollow ? 'bg-success' : 'bg-secondary']">
                  {{ row.dofollow ? '是' : '否' }}
                </span>
              </td>
              <td>
                <span :class="['badge', row.live ? 'bg-success' : 'bg-danger']">
                  {{ row.live ? '存活' : '失效' }}
                </span>
              </td>
              <td>{{ (row.relevance_score ?? 0).toFixed(2) }}</td>
              <td class="text-muted" style="font-size: 0.8rem">{{ row.first_seen ?? '—' }}</td>
              <td class="text-muted" style="font-size: 0.8rem">{{ row.last_checked ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </StateBlock>
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
  font-size: 0.9rem;
}
</style>
