<script setup lang="ts">
// Landing/smoke page (Plan 2026-06-18-002). Proves SPA -> /api/v1 wiring and
// exercises the U4 shell primitives: StateBlock (four-state) + the notifications
// store. The real publish workbench replaces this in U5.
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getJson } from '../api/client'
import StateBlock from '../components/StateBlock.vue'
import { useNotificationsStore } from '../stores/notifications'

interface Health {
  status: string
  api_version: string
  version: string
}

const notify = useNotificationsStore()
const health = useQuery({
  queryKey: ['health'],
  queryFn: () => getJson<Health>('/health'),
})

const blockState = computed<'loading' | 'error' | 'ready'>(() => {
  if (health.isPending.value) return 'loading'
  if (health.isError.value) return 'error'
  return 'ready'
})
</script>

<template>
  <section>
    <h1>控台就绪</h1>
    <StateBlock :state="blockState" :error="health.error.value" @retry="health.refetch()">
      <p>
        后端 <code>/api/v1</code> 在线 · API {{ health.data.value?.api_version }} ·
        版本 {{ health.data.value?.version }}
      </p>
      <button type="button" @click="notify.push('控台连接正常', 'success')">
        测试通知
      </button>
    </StateBlock>
  </section>
</template>
