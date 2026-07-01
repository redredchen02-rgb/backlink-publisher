<script setup lang="ts">
// Campaign progress — Plan P13 B3 (SPA migration).
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchCampaignStatus, type CampaignStatus } from '../../api/campaign'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()

const campaignId = computed(() => (route.params as Record<string, string>).campaignId || '')
const status = ref<CampaignStatus | null>(null)
const error = ref<Error | null>(null)
const loading = ref(true)
let pollTimer: ReturnType<typeof setTimeout> | null = null

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  if (!status.value) return 'empty'
  return 'ready'
})

const progressPct = computed(() => Math.round((status.value?.progress_pct ?? 0) * 100))

const load = async () => {
  if (!campaignId.value) return
  loading.value = true
  error.value = null
  try {
    status.value = await fetchCampaignStatus(campaignId.value)
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
  } finally {
    loading.value = false
  }
}

const startPolling = () => {
  const doPoll = async () => {
    try {
      status.value = await fetchCampaignStatus(campaignId.value)
    } catch {
      // Silently retry on next tick
    }
    if (status.value && !status.value.done) {
      pollTimer = setTimeout(doPoll, 2000)
    }
  }
  if (status.value && !status.value.done) {
    pollTimer = setTimeout(doPoll, 2000)
  }
}

const goBack = () => {
  router.push('/batch-campaign')
}

onMounted(async () => {
  await load()
  startPolling()
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<template>
  <section class="camp-progress">
    <header class="camp-progress__head">
      <h1>任务进度</h1>
      <button class="btn btn-sm btn-outline-secondary" @click="goBack">
        ← 返回批量任务
      </button>
    </header>

    <StateBlock
      :state="blockState"
      :error="error"
      :is-fetching="loading"
      empty-text="任务未找到。"
      @retry="load"
    >
      <div v-if="status" class="camp-progress__content">
        <div class="camp-progress__summary">
          <span class="badge" :class="status.done ? 'bg-success' : 'bg-primary'">
            {{ status.done ? '已完成' : '进行中' }}
          </span>
          <code class="ms-2">{{ status.campaign_id }}</code>
        </div>

        <div class="camp-progress__bar-wrap mt-3">
          <div class="d-flex justify-content-between mb-1">
            <span>进度</span>
            <span>{{ progressPct }}%</span>
          </div>
          <div class="progress" style="height: 20px">
            <div
              class="progress-bar"
              :class="status.done ? 'bg-success' : 'progress-bar-striped progress-bar-animated'"
              :style="{ width: progressPct + '%' }"
              :aria-valuenow="progressPct"
              aria-valuemin="0"
              aria-valuemax="100"
            />
          </div>
        </div>

        <div v-if="status.seeds?.length" class="data-table-wrap mt-3">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>内容</th>
              <th>状态</th>
              <th>草稿</th>
              <th>已发布</th>
              <th>错误</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="seed in status.seeds" :key="seed.idx">
              <td class="col-num">{{ seed.idx }}</td>
              <td class="col-text">
                <code class="text-truncate d-inline-block" style="max-width: 200px">
                  {{ seed.text_preview ?? '—' }}
                </code>
              </td>
              <td class="col-status">
                <span class="badge" :class="seed.status === 'success' ? 'bg-success' : 'bg-secondary'">
                  {{ seed.status }}
                </span>
              </td>
              <td class="col-num">{{ seed.draft_count ?? 0 }}</td>
              <td class="col-num">{{ seed.published_count ?? 0 }}</td>
              <td class="col-text text-danger">{{ seed.error ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        </div>

        <p v-if="status.running" class="text-muted mt-2">
          <span class="spinner-border spinner-border-sm me-1" role="status" />
          任务运行中...
        </p>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
.camp-progress {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.camp-progress__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.camp-progress__head h1 {
  margin: 0;
}
.camp-progress__summary {
  display: flex;
  align-items: center;
}
</style>
