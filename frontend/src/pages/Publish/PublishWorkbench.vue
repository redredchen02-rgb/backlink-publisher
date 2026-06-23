<script setup lang="ts">
// Core publish workbench — Plan 2026-06-18-002 U5.
//
// The four-stage single-publish flow (input → planned → validated → published),
// consuming the stateless /api/v1/pipeline/* endpoints via the publish store.
//
// Publish has NO pollable task-id (the backend publish path is synchronous; a
// background task store would change the credential-holding flow — deferred).
// So this is the DEGRADED busy-state branch the plan mandates:
//   - the submit control is disabled while in flight (a double-submit would race
//     the dedup.db single-flight);
//   - a busy panel (aria-live) tells the operator not to close the page;
//   - after a soft timeout the copy switches from "in progress" to "still
//     running / may already be done — don't resubmit" so it never looks frozen.
//
// Action failures are surfaced through the classifyError taxonomy into a toast
// (fixed copy, never raw server text); the result card branches on `state`.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { usePublishStore } from '../../stores/publish'
import { useNotificationsStore } from '../../stores/notifications'
import { classifyError } from '../../lib/errors'
import type { PlanRow } from '../../api/pipeline'
import type { Profile } from '../../api/profiles'
import ProfileSelector from '../../components/ProfileSelector.vue'

const store = usePublishStore()
const notify = useNotificationsStore()

const urlText = ref('')

// Busy-state soft timeout (degraded publish UX). Driven off the store's
// `publishing` flag via a watcher so the panel and the timeout share one source
// and the timer is trivially testable (toggle the flag, advance fake timers).
const SOFT_TIMEOUT_MS = 45_000
const softTimedOut = ref(false)
let softTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => store.publishing,
  (busy) => {
    if (softTimer) {
      clearTimeout(softTimer)
      softTimer = null
    }
    softTimedOut.value = false
    if (busy) {
      softTimer = setTimeout(() => {
        softTimedOut.value = true
      }, SOFT_TIMEOUT_MS)
    }
  },
)

onMounted(() => {
  store.loadPlatforms()
})
onUnmounted(() => {
  if (softTimer) clearTimeout(softTimer)
})

const busyCopy = computed(() =>
  softTimedOut.value
    ? '仍在进行，可能已完成，请勿重复提交 — 完成后自动刷新。'
    : '发布进行中，请勿关闭此页 — 完成后自动刷新。',
)

function field(row: PlanRow, key: string): string {
  const v = row[key]
  return typeof v === 'string' ? v : ''
}

function rowLabel(row: PlanRow): string {
  return field(row, 'custom_title') || field(row, 'title') || field(row, 'target_url') || '(无标题)'
}

function rowOutcome(row: PlanRow): { ok: boolean; text: string } {
  const url = field(row, 'published_url') || field(row, 'draft_url')
  if (url) return { ok: true, text: url }
  return { ok: false, text: field(row, 'error') || field(row, 'status') || '失败' }
}

function reportError(e: unknown): void {
  const c = classifyError(e)
  notify.push(`${c.title}：${c.message}`, 'error')
}

async function onPlan(): Promise<void> {
  store.setUrls(urlText.value)
  if (!store.urls.length) {
    notify.push('请先输入至少一个 URL', 'warning')
    return
  }
  try {
    await store.runPlan()
  } catch (e) {
    reportError(e)
  }
}

async function onValidate(): Promise<void> {
  try {
    await store.runValidate()
  } catch (e) {
    reportError(e)
  }
}

async function onPublish(): Promise<void> {
  if (store.publishing) return // belt-and-suspenders with the disabled button
  try {
    await store.runPublish()
    const r = store.publishResult
    if (r) {
      notify.push(
        `发布完成：${r.n_ok}/${r.n_total} 成功`,
        r.state === 'all_success' ? 'success' : 'warning',
      )
    }
  } catch (e) {
    reportError(e)
  }
}

function onReset(): void {
  urlText.value = ''
  store.reset()
}

const platformOptions = computed(() =>
  store.availablePlatforms.length
    ? store.availablePlatforms
    : [{ slug: store.config.platform, display_name: store.config.platform }],
)

// Apply a loaded publish preset onto the shared config. url_mode has no
// workbench control, so it is intentionally not mapped.
function applyProfile(p: Profile): void {
  store.config.platform = p.platform
  store.config.targetLanguage = p.language
  store.config.publishMode = p.publish_mode
}
</script>

<template>
  <section class="workbench">
    <h1>发布工作台</h1>

    <ol class="steps" :data-stage="store.stage" aria-label="发布流程进度">
      <li :class="{ 'steps__on': store.stage === 'input' }">1 · 输入</li>
      <li :class="{ 'steps__on': store.stage === 'planned' }">2 · 生成</li>
      <li :class="{ 'steps__on': store.stage === 'validated' }">3 · 验证</li>
      <li :class="{ 'steps__on': store.stage === 'published' }">4 · 发布</li>
    </ol>

    <!-- Config (shared across stages) -->
    <fieldset class="config">
      <legend>配置</legend>
      <label>
        平台
        <select v-model="store.config.platform">
          <option v-for="p in platformOptions" :key="p.slug" :value="p.slug">
            {{ p.display_name }}
          </option>
        </select>
      </label>
      <label>
        模式
        <select v-model="store.config.publishMode">
          <option value="publish">正式发布</option>
          <option value="draft">草稿</option>
        </select>
      </label>
      <label>
        语言
        <input v-model="store.config.targetLanguage" type="text" />
      </label>
      <label class="config__check">
        <input v-model="store.config.tier1" type="checkbox" />
        仅 Tier-1（dofollow）
      </label>
      <ProfileSelector
        class="config__profiles"
        :current="{
          platform: store.config.platform,
          language: store.config.targetLanguage,
          publishMode: store.config.publishMode,
        }"
        @apply="applyProfile"
      />
    </fieldset>

    <!-- Step 1 — input URLs -->
    <fieldset class="card">
      <legend>1 · 输入 URL</legend>
      <textarea
        v-model="urlText"
        rows="4"
        placeholder="每行一个 URL，第一行为主网域"
        aria-label="目标 URL（每行一个）"
      />
      <button type="button" :disabled="store.planning" @click="onPlan">
        {{ store.planning ? '生成中…' : '生成文章计划' }}
      </button>
    </fieldset>

    <!-- Step 2 — planned -->
    <fieldset v-if="store.plans.length" class="card">
      <legend>2 · 生成结果（{{ store.plans.length }} 篇）</legend>
      <ul class="rows">
        <li v-for="(row, i) in store.plans" :key="i">{{ rowLabel(row) }}</li>
      </ul>
      <button type="button" :disabled="store.validating" @click="onValidate">
        {{ store.validating ? '验证中…' : '验证' }}
      </button>
    </fieldset>

    <!-- Step 3 — validated → publish -->
    <fieldset v-if="store.validated.length" class="card">
      <legend>3 · 已验证（{{ store.validated.length }} 篇）</legend>
      <ul class="rows">
        <li v-for="(row, i) in store.validated" :key="i">{{ rowLabel(row) }}</li>
      </ul>

      <div v-if="store.publishing" class="publish-busy" role="status" aria-live="polite">
        <span class="spinner" aria-hidden="true" />
        <span class="publish-busy__copy">{{ busyCopy }}</span>
      </div>

      <button type="button" class="publish-btn" :disabled="store.publishing" @click="onPublish">
        {{ store.publishing ? '发布进行中…' : '发布' }}
      </button>
    </fieldset>

    <!-- Step 4 — result -->
    <fieldset
      v-if="store.publishResult"
      class="card result"
      :data-state="store.publishResult.state"
    >
      <legend>4 · 发布结果</legend>
      <p class="result__summary">
        {{ store.publishResult.n_ok }}/{{ store.publishResult.n_total }} 成功
        <span v-if="store.publishResult.state === 'partial_success'">（部分成功）</span>
      </p>
      <ul class="rows">
        <li v-for="(row, i) in store.publishResult.results" :key="i">
          <span :class="rowOutcome(row).ok ? 'ok' : 'fail'">
            {{ rowOutcome(row).ok ? '✓' : '✗' }}
          </span>
          {{ rowOutcome(row).text }}
        </li>
      </ul>
      <button type="button" @click="onReset">重新开始</button>
    </fieldset>
  </section>
</template>

<style scoped>
.workbench {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.steps {
  display: flex;
  gap: 0.75rem;
  list-style: none;
  padding: 0;
  margin: 0;
  color: var(--text-muted, #8b949e);
}
.steps__on {
  color: var(--text, #e6edf3);
  font-weight: 600;
}
.config,
.card {
  border: 1px solid var(--border, #30363d);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.config {
  flex-flow: row wrap;
  align-items: end;
  gap: 1rem;
}
.config label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.config__check {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}
.config__profiles {
  flex-basis: 100%;
  border-top: 1px solid var(--border, #30363d);
  padding-top: 0.5rem;
}
.rows {
  margin: 0;
  padding-left: 1.1rem;
  max-height: 12rem;
  overflow: auto;
}
.publish-busy {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  background: var(--warning-soft, #2d2410);
  color: var(--text, #e6edf3);
}
.spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid var(--border, #30363d);
  border-top-color: var(--accent, #58a6ff);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.result[data-state='all_success'] {
  border-color: var(--success, #3fb950);
}
.result[data-state='partial_success'] {
  border-color: var(--warning, #d29922);
}
.ok {
  color: var(--success, #3fb950);
}
.fail {
  color: var(--danger, #f85149);
}
</style>
