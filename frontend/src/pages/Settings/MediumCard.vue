<script setup lang="ts">
// Medium channel card (Plan 2026-06-18-002 U7, settings section 3 slice 3) — the
// per-channel ACTIONS, not a credential form. Medium's official API is archived, so
// the recommended path is a browser login: the launch/probe/clear actions consume
// the already-migrated POST /api/v1/settings/medium/*-browser-login endpoints, and
// the card hydrates readiness from GET /api/v1/settings/medium/status.
//
// The legacy Integration-Token block (save/clear-medium-token) stays on the old
// settings page until U8 — it's a stop-gap for old accounts and Medium no longer
// issues new tokens, so it doesn't justify migrating two more write endpoints now.
import { computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  getMediumStatus,
  launchMediumLogin,
  probeMediumLogin,
  clearMediumLogin,
  clearMediumOauth,
  type MediumActionResult,
} from '../../api/settings'
import { classifyError } from '../../lib/errors'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore, type Severity } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const qc = useQueryClient()

const query = useQuery({ queryKey: ['settings', 'medium-status'], queryFn: getMediumStatus })
const browser = computed(() => query.data.value?.browser ?? null)
const oauthTokenExists = computed(() => query.data.value?.oauth_token_exists ?? false)
const busy = computed(() => query.isFetching.value)

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

// Map the action envelope level → toast severity (danger is the odd one out).
function severityOf(level: string): Severity {
  if (level === 'danger') return 'error'
  if (level === 'success' || level === 'warning' || level === 'info') return level
  return 'info'
}

const badge = computed(() => {
  const s = browser.value?.state
  if (s === 'not_installed') return { cls: 'tag--err', text: '未安装 Playwright' }
  if (s === 'logged_in') return { cls: 'tag--ok', text: '浏览器已登录' }
  if (s === 'profile_exists_unverified') return { cls: 'tag--warn', text: '配置已就绪（未验证登录）' }
  return { cls: 'tag--muted', text: '浏览器配置未初始化' }
})

const playwrightMissing = computed(() => browser.value?.state === 'not_installed')

async function runAction(
  fn: () => Promise<MediumActionResult>,
  confirmMsg?: string,
): Promise<void> {
  if (confirmMsg && !window.confirm(confirmMsg)) return
  try {
    const r = await fn()
    notify.push(r.message, severityOf(r.level))
    await qc.invalidateQueries({ queryKey: ['settings', 'medium-status'] })
  } catch (e) {
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  }
}

async function onClearOauth(): Promise<void> {
  if (!window.confirm('确认清除 Medium OAuth token？发布时将改用浏览器登录态。')) return
  try {
    const r = await clearMediumOauth()
    notify.push(r.message, 'success')
    await qc.invalidateQueries({ queryKey: ['settings', 'medium-status'] })
  } catch (e) {
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  }
}
</script>

<template>
  <section class="card" aria-labelledby="medium-h">
    <h2 id="medium-h">Medium</h2>
    <p class="muted">
      Medium 官方 API 已于 2023 年归档，新用户请用浏览器登录：点一次完成登录后，后续发布自动复用登录态。
    </p>
    <StateBlock :state="state" :error="query.error.value" @retry="query.refetch()">
      <div class="medium__status">
        <span class="tag" :class="badge.cls" data-test="medium-badge">{{ badge.text }}</span>
        <small v-if="browser?.logged_in" class="muted">发布通道就绪</small>
        <small
          v-if="browser && browser.cookies_age_days !== null && browser.cookies_age_days > 30"
          class="muted"
        >（登录态陈旧，最后活动 {{ browser.cookies_age_days }} 天前）</small>
        <small v-if="browser?.singleton_lock_present" class="warn">
          检测到可能有 Chromium 实例在运行
        </small>
      </div>

      <p v-if="playwrightMissing" class="muted">
        未安装 Playwright，运行 <code>playwright install chromium</code> 后可使用浏览器登录。
      </p>
      <div v-else class="medium__actions">
        <button type="button" :disabled="busy" @click="runAction(launchMediumLogin)">
          打开浏览器登录
        </button>
        <button type="button" class="secondary" :disabled="busy" @click="runAction(probeMediumLogin)">
          测试登录状态
        </button>
        <button
          v-if="browser?.profile_has_cookies"
          type="button"
          class="danger"
          :disabled="busy"
          @click="runAction(clearMediumLogin, '确认清除浏览器登录？下次发布前需重新登录。')"
        >
          清除浏览器登录
        </button>
      </div>

      <div v-if="oauthTokenExists" class="medium__oauth">
        <span><span class="tag tag--ok">OAuth token 已存在</span> 发布时自动使用</span>
        <button type="button" class="danger" :disabled="busy" @click="onClearOauth">清除</button>
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
.warn {
  color: var(--warning);
  font-size: var(--text-sm);
}
.medium__status {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.medium__actions {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.medium__oauth {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.85rem;
  font-size: var(--text-base);
}
.secondary {
  background: transparent;
}
.danger {
  color: var(--danger);
  border-color: currentColor;
  background: transparent;
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
