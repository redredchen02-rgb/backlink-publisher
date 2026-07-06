<script setup lang="ts">
// Channel binding workbench (Plan 2026-06-18-002 U7, settings section 3 slice 2).
// Renders a credential form per FIXED-credential channel (token / token_fields /
// paste_blob / userpass), driven generically by the schema from
// GET /api/v1/settings/channels/forms. Bind-state (bound/identity) is joined from
// the read-only overview (same ['settings','channels'] cache as ChannelsCard) by
// slug. Submitting calls the already-migrated POST …/<channel>/credential.
//
// Secrets are never pre-filled: a password field shows a "已设置" placeholder when
// bound and a blank submit preserves the stored value (leave-as-is). oauth /
// browser-login channels are not here — they get card actions in a later slice.
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  getChannelForms,
  getChannels,
  saveChannelCredential,
  saveChannelToken,
  type ChannelBindingForm,
} from '../../api/settings'
import { ApiError } from '../../api/client'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useNotificationsStore } from '../../stores/notifications'
import { useSettingsDirtyStore } from '../../stores/settingsDirty'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const qc = useQueryClient()

// Plan 2026-07-06-005 W1 (D15): edit-surface query (hydrates `edits`) —
// window-focus refetch explicitly OFF. See
// docs/audits/2026-07-06-webui-refresh-inventory.md.
const formsQuery = useQuery({
  queryKey: ['settings', 'channel-forms'],
  queryFn: getChannelForms,
  refetchOnWindowFocus: false,
})
// Read-only status display (bound/identity badges), not hydrated into any
// editable field — inherits the site default (refetchOnWindowFocus: true).
const overviewQuery = useQuery({ queryKey: ['settings', 'channels'], queryFn: getChannels })

const forms = computed<ChannelBindingForm[]>(() => formsQuery.data.value?.forms ?? [])

const boundMap = computed<Record<string, { bound: boolean; identity: string | null }>>(() => {
  const m: Record<string, { bound: boolean; identity: string | null }> = {}
  for (const c of overviewQuery.data.value?.channels ?? []) {
    m[c.slug] = { bound: c.bound, identity: c.identity }
  }
  return m
})

const state = computed<FourState>(() => {
  if (formsQuery.isPending.value) return 'loading'
  if (formsQuery.isError.value) return 'error'
  return forms.value.length ? 'ready' : 'empty'
})

// Editable values, slug → fieldName → string. Seeded blank when the schema loads;
// kept local so edits don't fight the cached server state.
const edits = reactive<Record<string, Record<string, string>>>({})
const savingSlug = ref<string | null>(null)

// Plan 2026-07-06-005 W6 — shared save convention, per-slug variant: a 422
// renders inline under THAT slug's form (never a global toast), keyed by
// slug rather than by `useSettingsForm`'s single fieldMap because this card
// hosts N independent dynamic forms (one per fixed-credential channel) in
// one component instance — `useSettingsForm` assumes one form per instance,
// which doesn't fit here, so the same detail-extraction + no-toast-on-422
// behavior is reproduced directly (see useSettingsForm's module docstring
// for the same field-attribution caveat: the backend detail is a freeform
// string, not structured per-field data).
const formErrors = reactive<Record<string, string>>({})

function detailOf(payload: unknown): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const d = (payload as Record<string, unknown>).detail
    if (d != null) return String(d)
  }
  return '校验失败'
}

// Plan 2026-07-06-005 W2 — this card's hydration was already non-destructive
// (the loop below only ever seeds a *missing* field key blank, it never
// overwrites a key that's already present — so a refetch triggered while
// mid-edit never clobbers `edits`). What it lacked was dirty tracking for the
// route-leave guard / beforeunload handler.
//
// It deliberately does NOT reuse `useSnapshotDirty`'s single-baseline
// approach: that composable snapshots the *whole* source once and diffs
// against it, but here new keys get seeded into `edits` incrementally as
// more channel forms/fields stream in (each seed pass would otherwise look
// like "the user changed something" even though nothing was typed). Instead,
// `lastSeeded` mirrors only the seeded *blank defaults* — every key in it is
// updated in lockstep with `edits` at seed time (both blank, so no apparent
// diff) and left alone afterwards, so a real edit is exactly the divergence
// between `edits` and `lastSeeded` for that key. Reactive (not a plain
// object) so `markSlugClean()` — called after a successful save, even one
// that doesn't itself mutate `edits` (the "清除" path) — reliably triggers
// the `dirty` computed below to re-evaluate.
const lastSeeded = reactive<Record<string, Record<string, string>>>({})

function markSlugClean(slug: string): void {
  lastSeeded[slug] = { ...(edits[slug] ?? {}) }
}

watch(
  () => formsQuery.data.value,
  (data) => {
    for (const f of data?.forms ?? []) {
      if (!edits[f.slug]) edits[f.slug] = {}
      if (!lastSeeded[f.slug]) lastSeeded[f.slug] = {}
      for (const fld of f.fields) {
        if (!(fld.name in edits[f.slug])) {
          edits[f.slug][fld.name] = ''
          lastSeeded[f.slug][fld.name] = ''
        }
      }
    }
  },
  { immediate: true },
)

const dirty = computed(() => JSON.stringify(edits) !== JSON.stringify(lastSeeded))

const dirtyStore = useSettingsDirtyStore()
watch(
  dirty,
  (v) => {
    if (v) dirtyStore.setDirty('settings-channel-binding', '渠道凭据绑定')
    else dirtyStore.clearDirty('settings-channel-binding')
  },
  { immediate: true },
)
onUnmounted(() => dirtyStore.clearDirty('settings-channel-binding'))

function isBound(slug: string): boolean {
  return Boolean(boundMap.value[slug]?.bound)
}

function fieldPlaceholder(slug: string, field: ChannelBindingForm['fields'][number]): string {
  if (isBound(slug) && field.secret) return '已设置 — 空白表示保留现有值'
  return field.placeholder
}

function clearSecretInputs(form: ChannelBindingForm): void {
  for (const fld of form.fields) {
    if (fld.secret) edits[form.slug][fld.name] = ''
  }
}

async function submit(form: ChannelBindingForm, clear: boolean): Promise<void> {
  if (savingSlug.value) return
  savingSlug.value = form.slug
  delete formErrors[form.slug]
  try {
    const body: Record<string, string | number> = { auth_type: form.auth_type }
    if (clear) {
      body.clear = 1
    } else {
      for (const fld of form.fields) body[fld.name] = edits[form.slug][fld.name] ?? ''
    }
    // devto / ghpages persist via the dedicated token-paste route; the rest via the
    // generic credential dispatch. Both take the same body + return the same shape.
    const save = form.save_via === 'token' ? saveChannelToken : saveChannelCredential
    const r = await save(form.slug, body)
    notify.push(r.message, r.ok ? 'success' : 'info')
    if (!clear) clearSecretInputs(form)
    // This slug's fields now match what was just persisted — re-baseline so
    // it stops counting toward the route-leave guard's dirty set. (The
    // `clear` path never touched `edits`, but re-baselining is still correct
    // and cheap: it's a no-op diff-wise.)
    markSlugClean(form.slug)
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['settings', 'channels'] }),
      qc.invalidateQueries({ queryKey: ['settings', 'channel-forms'] }),
    ])
  } catch (e) {
    // 422 = a credential failed a validation gate (SSRF / cookie schema / hostname
    // / both-userpass-required); the problem+json detail is the server-sanitized,
    // actionable message — W6: rendered inline under THIS slug's form, never a
    // global toast (see the `formErrors` comment above `edits`).
    if (e instanceof ApiError && e.status === 422) {
      formErrors[form.slug] = detailOf(e.payload)
      return
    }
    toastError(e)
  } finally {
    savingSlug.value = null
  }
}
</script>

<template>
  <section class="card" aria-labelledby="bind-h">
    <h2 id="bind-h">渠道凭据绑定</h2>
    <p class="muted">
      为各发布渠道写入登录凭据（保存到本机 0600 权限文件）。密码类字段留空表示保留现有值。
      OAuth / 浏览器登录渠道（Blogger · Medium · velog）见下方各自的动作卡。
    </p>
    <StateBlock
      :state="state"
      :error="formsQuery.error.value"
      empty-text="无可直接填表绑定的渠道。"
      @retry="formsQuery.refetch()"
    >
      <details v-for="f in forms" :key="f.slug" class="bind" data-test="bind">
        <summary>
          <strong>{{ f.display_name }}</strong>
          <span class="tag tag--muted">{{ f.auth_type }}</span>
          <span class="tag" :class="isBound(f.slug) ? 'tag--ok' : 'tag--muted'">
            {{ isBound(f.slug) ? '已绑定' : '未绑定' }}
          </span>
          <span v-if="boundMap[f.slug]?.identity" class="muted bind__id">
            {{ boundMap[f.slug]?.identity }}
          </span>
        </summary>

        <form class="bind__form" @submit.prevent="submit(f, false)">
          <div v-for="fld in f.fields" :key="fld.name" class="field">
            <label :for="`${f.slug}-${fld.name}`">{{ fld.label }}</label>
            <textarea
              v-if="fld.type === 'textarea'"
              :id="`${f.slug}-${fld.name}`"
              v-model="edits[f.slug][fld.name]"
              rows="5"
              spellcheck="false"
              autocomplete="off"
              :placeholder="fieldPlaceholder(f.slug, fld)"
            />
            <input
              v-else
              :id="`${f.slug}-${fld.name}`"
              v-model="edits[f.slug][fld.name]"
              :type="fld.type === 'password' ? 'password' : fld.type === 'url' ? 'url' : 'text'"
              spellcheck="false"
              autocomplete="off"
              :placeholder="fieldPlaceholder(f.slug, fld)"
            />
            <small v-if="fld.help" class="muted">{{ fld.help }}</small>
          </div>

          <p v-if="formErrors[f.slug]" class="form-error" :data-test="`bind-error-${f.slug}`">
            {{ formErrors[f.slug] }}
          </p>

          <div class="bind__actions">
            <button type="submit" :disabled="savingSlug === f.slug">
              {{ savingSlug === f.slug ? '保存中…' : isBound(f.slug) ? '更新' : '绑定' }}
            </button>
            <button
              v-if="f.supports_clear && isBound(f.slug)"
              type="button"
              class="danger"
              :disabled="savingSlug === f.slug"
              @click="submit(f, true)"
            >
              清除
            </button>
          </div>
        </form>
      </details>
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
.bind {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-bottom: 0.6rem;
  overflow: hidden;
}
.bind > summary {
  padding: 0.6rem 0.85rem;
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.bind__id {
  margin-left: auto;
}
.bind__form {
  padding: 0.2rem 0.85rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.field input,
.field textarea {
  padding: var(--control-pad-y) var(--control-pad-x);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-base);
}
.field textarea {
  resize: vertical;
}
.bind__actions {
  display: flex;
  gap: 0.6rem;
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
.tag--muted {
  color: var(--text-secondary);
}
.form-error {
  color: var(--danger);
  font-size: var(--text-sm);
  margin: 0.25rem 0 0;
}
</style>
