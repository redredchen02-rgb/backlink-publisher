<script setup lang="ts">
// Settings page (Plan 2026-06-18-002 U7) — built section-by-section, now COMPLETE:
// global config (keyword pools + publish cadence), channel binding + per-channel
// action cards (Medium / velog / Blogger / Blog-ID), and AI integration (LLM +
// cover-image). As of §5 the console nav points here (navItems `to`), so this is
// the PRIMARY settings entry; the legacy Jinja /settings page survives only until
// U8 retirement (a few legacy-only escape hatches still link out to it).
import { computed, reactive, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  getKeywordPools,
  saveKeywordPools,
  getScheduleSettings,
  saveScheduleSettings,
  type ScheduleSettings,
} from '../../api/settings'
import { useSnapshotDirty } from '../../composables/useSnapshotDirty'
import { useSettingsForm } from '../../composables/useSettingsForm'
import StateBlock from '../../components/StateBlock.vue'
import ChannelsCard from './ChannelsCard.vue'
import ChannelBindingCard from './ChannelBindingCard.vue'
import MediumCard from './MediumCard.vue'
import VelogCard from './VelogCard.vue'
import BloggerCard from './BloggerCard.vue'
import NotionCard from './NotionCard.vue'
import BlogIdsCard from './BlogIdsCard.vue'
import LlmSettingsCard from './LlmSettingsCard.vue'
import SettingsSidebar from './SettingsSidebar.vue'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

// ── keyword pools ────────────────────────────────────────────────────────────

// Plan 2026-07-06-005 W1 (D15): this is an edit-surface query (hydrates
// `keywordEdits`, a live textarea) — window-focus refetch is explicitly OFF so
// switching back to this tab never re-fires a fetch mid-edit. This does not
// by itself fix the hydration-overwrite bug (a refetch from cache
// invalidation elsewhere still rewrites `keywordEdits`); that dirty-aware fix
// is W2's scope. See docs/audits/2026-07-06-webui-refresh-inventory.md.
const keywordsQuery = useQuery({
  queryKey: ['settings', 'keywords'],
  queryFn: getKeywordPools,
  refetchOnWindowFocus: false,
})
const keywordTargets = computed<string[]>(() => keywordsQuery.data.value?.targets ?? [])

// Editable copy: domain → textarea string (one keyword per line). Hydrated from
// the query and kept local so edits don't fight TanStack's cached server state.
const keywordEdits = reactive<Record<string, string>>({})

// Plan 2026-07-06-005 W2 — the hydration-overwrite bug fix. Before this, the
// watch below unconditionally overwrote `keywordEdits` any time
// `keywordsQuery.data` changed — including a refetch fired by *anything*
// other than window focus (query invalidation elsewhere, a manual refetch,
// coming back from another route), silently discarding whatever the user had
// typed and not yet saved. `keywordsDirty` guards that: while the user has
// unsaved edits, hydration is skipped entirely; `markKeywordsClean()` re-
// baselines right after a hydration actually runs (including the one
// triggered by this card's own successful save, so the post-save refetch's
// echo of what was just submitted doesn't itself look "dirty").
const { dirty: keywordsDirty, markClean: markKeywordsClean } = useSnapshotDirty(
  'settings-keywords',
  'SEO 关键词池',
  () => keywordEdits,
)

// Plan 2026-07-06-005 W6 — shared save convention: 422 renders inline
// (`keywordsFormError`, no fixed field set — the >60-char rule can hit any
// domain's pool, and the detail doesn't name which one), success toast +
// this section's `markKeywordsClean()`, per-section `saving` busy.
const { saving: savingKeywords, formError: keywordsFormError, run: runKeywords } = useSettingsForm(
  markKeywordsClean,
)

watch(
  () => keywordsQuery.data.value,
  (data) => {
    if (!data) return
    if (keywordsDirty.value) return
    for (const domain of data.targets) {
      keywordEdits[domain] = (data.pools[domain] ?? []).join('\n')
    }
    markKeywordsClean()
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
  const pools: Record<string, string[]> = {}
  for (const domain of keywordTargets.value) pools[domain] = poolLines(domain)
  // markKeywordsClean() (via useSettingsForm's markClean callback) fires
  // before the refetch below, same ordering as before W6, so the hydration
  // watch (guarded above) is allowed to run when the saved data comes back.
  const result = await runKeywords(() => saveKeywordPools(pools), {
    successMessage: '关键词已保存',
  })
  if (result) await keywordsQuery.refetch()
}

// ── publish cadence ──────────────────────────────────────────────────────────

// Plan 2026-07-06-005 W1 (D15): edit-surface query (hydrates `scheduleForm`) —
// window-focus refetch explicitly OFF; see the identical rationale on
// `keywordsQuery` above.
const scheduleQuery = useQuery({
  queryKey: ['settings', 'schedule'],
  queryFn: getScheduleSettings,
  refetchOnWindowFocus: false,
})
const scheduleForm = reactive<ScheduleSettings>({ min_interval_hours: 4, jitter_minutes: 30 })

// Plan 2026-07-06-005 W2 — same hydration-overwrite fix as the keyword pool
// editor above; see that block's comment for the full rationale.
const { dirty: scheduleDirty, markClean: markScheduleClean } = useSnapshotDirty(
  'settings-schedule',
  '排程发布设定',
  () => scheduleForm,
)

// Plan 2026-07-06-005 W6 — shared save convention: 422 renders inline
// (`scheduleFormError`; the "填数字" rejection doesn't name which of the two
// numeric fields failed, so no `fieldMap`), success toast + this section's
// `markScheduleClean()`, per-section `saving` busy.
const { saving: savingSchedule, formError: scheduleFormError, run: runSchedule } = useSettingsForm(
  markScheduleClean,
)

watch(
  () => scheduleQuery.data.value,
  (data) => {
    if (!data) return
    if (scheduleDirty.value) return
    scheduleForm.min_interval_hours = data.min_interval_hours ?? 4
    scheduleForm.jitter_minutes = data.jitter_minutes ?? 30
    markScheduleClean()
  },
  { immediate: true },
)

const scheduleState = computed<FourState>(() => {
  if (scheduleQuery.isPending.value) return 'loading'
  if (scheduleQuery.isError.value) return 'error'
  return 'ready'
})

async function onSaveSchedule(): Promise<void> {
  const result = await runSchedule(
    () =>
      saveScheduleSettings({
        min_interval_hours: Number(scheduleForm.min_interval_hours),
        jitter_minutes: Number(scheduleForm.jitter_minutes),
      }),
    { successMessage: '排程设定已保存' },
  )
  if (result) await scheduleQuery.refetch()
}
</script>

<template>
  <section class="settings">
    <header class="settings__head">
      <h1>设置</h1>
      <p class="muted">
        渠道绑定与动作 · 全局配置（关键词池 · 排程） · AI 整合（LLM · 封面图）——全部在此页管理。
      </p>
    </header>

    <div class="settings__layout">
      <SettingsSidebar class="settings__nav" />

      <div class="settings__main">
        <!-- channel binding status (read-only overview) -->
        <div id="sec-channels"><ChannelsCard /></div>

        <!-- channel credential binding forms (fixed-credential auth types) -->
        <div id="sec-binding"><ChannelBindingCard /></div>

        <!-- per-channel action cards (browser-login / oauth) -->
        <div id="sec-medium"><MediumCard /></div>
        <div id="sec-velog"><VelogCard /></div>
        <div id="sec-blogger"><BloggerCard /></div>
        <div id="sec-notion"><NotionCard /></div>
        <div id="sec-blogids"><BlogIdsCard /></div>

        <!-- SEO anchor keyword pools -->
        <section id="sec-keywords" class="card" aria-labelledby="kw-h">
      <h2 id="kw-h">SEO 锚文本关键词池</h2>
      <p class="muted">
        生成的外链文章从这里选关键词作锚文本，替代裸域名。每个 target 建议 5–10 个；一行一个，
        去前后空白，≤60 字符，重复自动去重。
      </p>
      <StateBlock
        :state="keywordState"
        :error="keywordsQuery.error.value"
        empty-text="暂无已知 target 站——请先在上方「Blogger Blog ID 映射」配置。"
        @retry="keywordsQuery.refetch()"
      >
        <form data-test="keyword-form" @submit.prevent="onSaveKeywords">
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
          <p v-if="keywordsFormError" class="form-error" data-test="keywords-form-error">
            {{ keywordsFormError }}
          </p>
          <button type="submit" :disabled="savingKeywords">
            {{ savingKeywords ? '保存中…' : '保存所有关键词池' }}
          </button>
        </form>
      </StateBlock>
    </section>

        <!-- publish cadence -->
        <section id="sec-schedule" class="card" aria-labelledby="sch-h">
      <h2 id="sch-h">排程发布设定</h2>
      <p class="muted">控制草稿队列的发布节奏，避免短时间大量上稿被平台识别。</p>
      <StateBlock
        :state="scheduleState"
        :error="scheduleQuery.error.value"
        @retry="scheduleQuery.refetch()"
      >
        <form class="sched" data-test="schedule-form" @submit.prevent="onSaveSchedule">
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
          <p v-if="scheduleFormError" class="form-error" data-test="schedule-form-error">
            {{ scheduleFormError }}
          </p>
          <button type="submit" :disabled="savingSchedule">
            {{ savingSchedule ? '保存中…' : '保存设定' }}
          </button>
        </form>
      </StateBlock>
    </section>

        <!-- AI integration (LLM + image-gen) -->
        <div id="sec-ai"><LlmSettingsCard /></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 1000px;
}
.settings__layout {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 1.5rem;
  align-items: start;
}
.settings__main {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  min-width: 0;
}
@media (max-width: 720px) {
  .settings__layout {
    grid-template-columns: 1fr;
  }
  .settings__nav {
    display: none;
  }
}
.settings__head h1 {
  margin: 0 0 0.25rem;
}
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
.kw-domain {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
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
  color: var(--text-secondary);
  font-size: var(--text-xs);
}
.kw-domain textarea {
  width: 100%;
  margin: 0.4rem 0 0.75rem;
  font-family: var(--font-mono, monospace);
  font-size: var(--text-base);
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
  padding: var(--control-pad-y) var(--control-pad-x);
}
button[type='submit'] {
  margin-top: 0.75rem;
}
.form-error {
  color: var(--danger);
  font-size: var(--text-sm);
  margin: 0.5rem 0 0;
}
</style>
