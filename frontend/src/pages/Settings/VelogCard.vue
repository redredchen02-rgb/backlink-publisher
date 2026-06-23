<script setup lang="ts">
// Velog channel card (Plan 2026-06-18-002 U7, settings section 3 slice 4) — the
// per-channel action card. Velog publishes via a browser-login: the bind button
// spawns a headed velog-login window (POST /api/v1/settings/velog/login), and the
// card hydrates the 6-state status from GET /api/v1/settings/velog/status.
import { computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { getVelogStatus, velogLogin } from '../../api/settings'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore, type Severity } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const qc = useQueryClient()

const query = useQuery({ queryKey: ['settings', 'velog-status'], queryFn: getVelogStatus })
const vs = computed(() => query.data.value ?? null)
const busy = computed(() => query.isFetching.value)

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

const badge = computed(() => {
  const s = vs.value?.state
  if (s === 'fresh' || s === 'ok') return 'tag--ok'
  if (s === 'warn') return 'tag--warn'
  if (s === 'cap_reached' || s === 'permission_denied') return 'tag--muted'
  return 'tag--err'
})

// A never-bound channel uses "绑定 velog"; any other state offers a re-bind.
const bindLabel = computed(() => (vs.value?.state === 'err' ? '绑定 velog' : '重新绑定'))
const bound = computed(() => vs.value?.state === 'ok' || vs.value?.state === 'fresh')

async function onLogin(): Promise<void> {
  try {
    const r = await velogLogin()
    const sev: Severity = r.ok ? 'success' : 'warning'
    notify.push(r.message, sev)
    await qc.invalidateQueries({ queryKey: ['settings', 'velog-status'] })
  } catch (e) {
    toastError(e)
  }
}
</script>

<template>
  <section class="card" aria-labelledby="velog-h">
    <h2 id="velog-h">velog</h2>
    <p class="muted">
      velog.io 通过浏览器登录发布。点「绑定」会弹出 Chromium 完成社交登录，凭证存于本机
      <code>velog-cookies.json</code>（0600，约 30 天有效）。
    </p>
    <StateBlock :state="state" :error="query.error.value" @retry="query.refetch()">
      <div v-if="vs" class="velog__status">
        <span class="tag" :class="badge" data-test="velog-badge">{{ vs.label }}</span>
        <small v-if="bound && vs.count !== undefined" class="muted">
          今日已发 {{ vs.count }} / {{ vs.cap }} · UTC 午夜重置
        </small>
      </div>

      <div
        v-if="vs && vs.guide && !bound"
        class="velog__guide muted"
        data-test="velog-guide"
      >
        需要操作：<code>{{ vs.guide }}</code>
      </div>

      <div class="velog__actions">
        <button type="button" :disabled="busy" @click="onLogin">{{ bindLabel }}</button>
        <small v-if="bound && vs?.cookies_path" class="muted">
          凭证：<code>{{ vs.cookies_path }}</code>
        </small>
      </div>
    </StateBlock>
  </section>
</template>

<style scoped>
.card {
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 1.25rem;
}
.card h2 {
  margin: 0 0 0.5rem;
  font-size: var(--text-xl);
}
.muted {
  color: var(--text-secondary);
  font-size: var(--text-base);
}
.velog__status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}
.velog__guide {
  margin-bottom: 0.6rem;
}
.velog__actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.tag {
  font-size: var(--text-xs);
  padding: 0.05rem var(--control-pad-x);
  border-radius: var(--radius-pill);
  border: 1px solid var(--border);
}
.tag--ok {
  color: var(--success);
  border-color: currentColor;
}
.tag--warn {
  color: var(--warning);
  border-color: currentColor;
}
.tag--err {
  color: var(--danger);
  border-color: currentColor;
}
.tag--muted {
  color: var(--text-secondary);
}
</style>
