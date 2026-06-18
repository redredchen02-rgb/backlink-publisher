<script setup lang="ts">
// Smoke page (Plan 2026-06-18-002 U3): proves the SPA -> /api/v1 wiring end to
// end via TanStack Query (declarative fetch/loading/error). Real workbench/
// monitor pages land in U4-U6.
import { useQuery } from '@tanstack/vue-query'
import { getJson } from '../api/client'
import { classifyError } from '../lib/errors'

interface Health {
  status: string
  api_version: string
  version: string
}
interface AppConfig {
  lite_edition: boolean
  llm_configured: boolean
  pro_status: { configured: boolean; model?: string }
}

const health = useQuery({
  queryKey: ['health'],
  queryFn: () => getJson<Health>('/health'),
})
const config = useQuery({
  queryKey: ['app-config'],
  queryFn: () => getJson<AppConfig>('/app-config'),
})
</script>

<template>
  <section>
    <h1>控台就绪</h1>

    <p v-if="health.isPending.value" class="muted">正在连接后端…</p>
    <p v-else-if="health.isError.value" class="muted">
      {{ classifyError(health.error.value).title }}
    </p>
    <p v-else>
      后端 <code>/api/v1</code> 在线 · API {{ health.data.value?.api_version }} ·
      版本 {{ health.data.value?.version }}
    </p>

    <ul v-if="config.data.value">
      <li>Lite 版：{{ config.data.value.lite_edition ? '是' : '否' }}</li>
      <li>Pro/LLM 已配置：{{ config.data.value.llm_configured ? '是' : '否' }}</li>
    </ul>
  </section>
</template>
