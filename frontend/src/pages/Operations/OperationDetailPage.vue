<script setup lang="ts">
// Operation detail — Plan 2026-07-09 (U3).
//
// Deep-linkable view of one async op; embeds OperationProgress (which polls and
// shows the step indicator + progress + cancel + result). Reachable from the
// task center or directly after submitting a publish.
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import OperationProgress from '../../components/OperationProgress.vue'

const route = useRoute()
const router = useRouter()

const opId = computed(() => (route.params as Record<string, string>).opId || '')

const goBack = (): void => {
  router.push('/operations')
}
</script>

<template>
  <section class="op-detail container py-3">
    <header class="d-flex align-items-center justify-content-between mb-3">
      <h1 class="h4 mb-0">任务详情</h1>
      <button class="btn btn-sm btn-outline-secondary" @click="goBack">← 返回任务中心</button>
    </header>

    <div v-if="opId" class="card p-3">
      <p class="text-muted small mb-3"><code>{{ opId }}</code></p>
      <OperationProgress :op-id="opId" />
    </div>
    <p v-else class="text-muted">缺少任务 id。</p>
  </section>
</template>
