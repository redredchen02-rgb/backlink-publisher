<script setup lang="ts">
// Settings page (Plan 2026-06-18-002 U7) — built section-by-section. This first
// slice is the GLOBAL config (keyword pools + publish cadence), consuming the
// GlobalSettingsAPI GET/POST endpoints. The channel / LLM / OAuth / diagnostics
// sections land in later slices; until the page is complete the sidebar keeps the
// LEGACY /settings link (navItems href), so this SPA route is dev-reachable by URL
// but not yet advertised (no UX regression: the legacy page still has every form).
import { computed, reactive, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  getKeywordPools,
  saveKeywordPools,
  getScheduleSettings,
  saveScheduleSettings,
  type ScheduleSettings,
} from '../../api/settings'
import { ApiError } from '../../api/client'
import { classifyError } from '../../lib/errors'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()

// ── keyword pools ────────────────────────────────────────────────────────────

const keywordsQuery = useQuery({ queryKey: ['settings', 'keywords'], queryFn: getKeywordPools })
const keywordTargets = computed<string[]>(() => keywordsQuery.data.value?.targets ?? [])

// Editable copy: domain → textarea string (one keyword per line). Hydrated from
// the query and kept local so edits don't fight TanStack's cached server state.
const keywordEdits = reactive<Record<string, string>>({})
const savingKeywords = ref(false)

watch(
  () => keywordsQuery.data.value,
  (data) => {
    if (!data) return
    for (const domain of data.targets) {
      keywordEdits[domain] = (data.pools[domain] ?? []).join('\n')
    }
  },
  { immediate: true },
)

const keywordState = computed<FourState>(() => {
  if (keywordsQuery.isPending.value) return 'loading'
  if (keywordsQuery.isError.value) return 'error'
  return keywordTargets.value.length ? 'ready' : 'empty'
})

function poolLines(domain: string): string[] {
  return (keywordEdits[domain] ?? '').split('\n').map((s) => s.trim()).filter(Boolean)
}

function poolCount(domain: string): string {
  const n = poolLines(domain).length
  return n ? `${n} 个关键词` : '未配置'
}

async function onSaveKeywords(): Promise<void> {
  if (savingKeywords.value) return
  savingKeywords.value = true
  try {
    const pools: Record<string, string[]> = {}
    for (const domain of keywordTargets.value) pools[domain] = poolLines(domain)
    const r = await saveKeywordPools(pools)
    notify.push(r.message || '关键词已保存', 'success')
    await keywordsQuery.refetch()
  } catch (e) {
    // 422 = a keyword failed the >60-char rule; the problem+json detail is the
    // server-sanitized, actionable message (rendered text-only by the toast).
    if (e instanceof ApiError && e.status === 422) {
      const detail = (e.payload as { detail?: string })?.detail
      notify.push(detail || '关键词校验失败（需 ≤60 字符）', 'warning')
      return
    }
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  } finally {
    savingKeywords.value = false
  }
}

// ── publish cadence ──────────────────────────────────────────────────────────

const scheduleQuery = useQuery({ queryKey: ['settings', 'schedule'], queryFn: getScheduleSettings })
const scheduleForm = reactive<ScheduleSettings>({ min_interval_hours: 4, jitter_minutes: 30 })
const savingSchedule = ref(false)

watch(
  () => scheduleQuery.data.value,
  (data) => {
    if (!data) return
    scheduleForm.min_interval_hours = data.min_interval_hours ?? 4
    scheduleForm.jitter_minutes = data.jitter_minutes ?? 30
  },
  { immediate: true },
)

const scheduleState = computed<FourState>(() => {
  if (scheduleQuery.isPending.value) return 'loading'
  if (scheduleQuery.isError.value) return 'error'
  return 'ready'
})

async function onSaveSchedule(): Promise<void> {
  if (savingSchedule.value) return
  savingSchedule.value = true
  try {
    const r = await saveScheduleSettings({
      min_interval_hours: Number(scheduleForm.min_interval_hours),
      jitter_minutes: Number(scheduleForm.jitter_minutes),
    })
    notify.push(r.message || '排程设定已保存', 'success')
    await scheduleQuery.refetch()
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      notify.push('排程数值无效（请填数字）', 'warning')
      return
    }
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  } finally {
    savingSchedule.value = false
  }
}
</script>

<template>
  <section class="settings">
    <header class="settings__head">
      <h1>设置</h1>
      <p class="muted">
        全局配置（关键词池 · 排程节奏）。渠道凭证 / LLM / OAuth 仍在
        <a href="/settings">旧设置页</a>，正逐段迁入。
      </p>
    </header>

    <!-- SEO anchor keyword pools -->
    <section class="card" aria-labelledby="kw-h">
      <h2 id="kw-h">SEO 锚文本关键词池</h2>
      <p class="muted">
        生成的外链文章从这里选关键词作锚文本，替代裸域名。每个 target 建议 5–10 个；一行一个，
        去前后空白，≤60 字符，重复自动去重。
      </p>
      <StateBlock
        :state="keywordState"
        :error="keywordsQuery.error.value"
        empty-text="暂无已知 target 站——请先在旧设置页配置 Blogger Blog ID 映射。"
        @retry="keywordsQuery.refetch()"
      >
        <form @submit.prevent="onSaveKeywords">
          <details v-for="domain in keywordTargets" :key="domain" class="kw-domain">
            <summary>
              <strong>{{ domain }}</strong>
              <span class="kw-count">{{ poolCount(domain) }}</span>
            </summary>
            <label :for="`kw-${domain}`" class="muted">关键词（每行一个）：</label>
            <textarea
              :id="`kw-${domain}`"
              v-model="keywordEdits[domain]"
              rows="4"
              spellcheck="false"
              placeholder="品牌词&#10;行业关键词&#10;长尾短语…"
            />
          </details>
          <button type="submit" :disabled="savingKeywords">
            {{ savingKeywords ? '保存中…' : '保存所有关键词池' }}
          </button>
        </form>
      </StateBlock>
    </section>

    <!-- publish cadence -->
    <section class="card" aria-labelledby="sch-h">
      <h2 id="sch-h">排程发布设定</h2>
      <p class="muted">控制草稿队列的发布节奏，避免短时间大量上稿被平台识别。</p>
      <StateBlock
        :state="scheduleState"
        :error="scheduleQuery.error.value"
        @retry="scheduleQuery.refetch()"
      >
        <form class="sched" @submit.prevent="onSaveSchedule">
          <div class="field">
            <label for="min-int">最小发布间隔（小时）</label>
            <input
              id="min-int"
              v-model.number="scheduleForm.min_interval_hours"
              type="number"
              min="0.5"
              max="168"
              step="0.5"
            />
            <small class="muted">两篇之间最少间隔小时数（建议 4–24h）</small>
          </div>
          <div class="field">
            <label for="jitter">随机抖动（±分钟）</label>
            <input
              id="jitter"
              v-model.number="scheduleForm.jitter_minutes"
              type="number"
              min="0"
              max="120"
              step="5"
            />
            <small class="muted">在间隔上随机增减的分钟数，模拟自然节奏</small>
          </div>
          <button type="submit" :disabled="savingSchedule">
            {{ savingSchedule ? '保存中…' : '保存设定' }}
          </button>
        </form>
      </StateBlock>
    </section>
  </section>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 760px;
}
.settings__head h1 {
  margin: 0 0 0.25rem;
}
.card {
  background: var(--bg-raised, #161b22);
  border: 1px solid var(--border, #30363d);
  border-radius: 10px;
  padding: 1.25rem;
}
.card h2 {
  margin: 0 0 0.5rem;
  font-size: 1.05rem;
}
.muted {
  color: var(--text-secondary, #8b949e);
  font-size: 0.85rem;
}
.kw-domain {
  border: 1px solid var(--border, #30363d);
  border-radius: 8px;
  margin-bottom: 0.75rem;
  overflow: hidden;
}
.kw-domain > summary {
  padding: 0.6rem 0.85rem;
  cursor: pointer;
  user-select: none;
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}
.kw-count {
  color: var(--text-secondary, #8b949e);
  font-size: 0.78rem;
}
.kw-domain textarea {
  width: 100%;
  margin: 0.4rem 0 0.75rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
}
.kw-domain label {
  display: block;
  padding: 0 0.85rem;
}
.kw-domain textarea {
  width: calc(100% - 1.7rem);
  margin-left: 0.85rem;
}
.sched {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: flex-end;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.field input {
  padding: 0.4rem 0.5rem;
}
button[type='submit'] {
  margin-top: 0.75rem;
}
</style>
