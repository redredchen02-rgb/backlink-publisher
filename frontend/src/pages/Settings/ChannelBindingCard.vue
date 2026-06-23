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
import { computed, reactive, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  getChannelForms,
  getChannels,
  saveChannelCredential,
  saveChannelToken,
  type ChannelBindingForm,
} from '../../api/settings'
import { ApiError } from '../../api/client'
import { classifyError } from '../../lib/errors'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const qc = useQueryClient()

const formsQuery = useQuery({ queryKey: ['settings', 'channel-forms'], queryFn: getChannelForms })
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

watch(
  () => formsQuery.data.value,
  (data) => {
    for (const f of data?.forms ?? []) {
      if (!edits[f.slug]) edits[f.slug] = {}
      for (const fld of f.fields) {
        if (!(fld.name in edits[f.slug])) edits[f.slug][fld.name] = ''
      }
    }
  },
  { immediate: true },
)

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
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['settings', 'channels'] }),
      qc.invalidateQueries({ queryKey: ['settings', 'channel-forms'] }),
    ])
  } catch (e) {
    // 422 = a credential failed a validation gate (SSRF / cookie schema / hostname
    // / both-userpass-required); the problem+json detail is the server-sanitized,
    // actionable message (rendered text-only by the toast).
    if (e instanceof ApiError && e.status === 422) {
      const detail = (e.payload as { detail?: string })?.detail
      notify.push(detail || '凭据校验失败', 'warning')
      return
    }
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
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
  border-radius: 10px;
  padding: 1.25rem;
}
.card h2 {
  margin: 0 0 0.5rem;
  font-size: 1.05rem;
}
.muted {
  color: var(--text-secondary);
  font-size: 0.85rem;
}
.bind {
  border: 1px solid var(--border);
  border-radius: 8px;
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
  padding: 0.4rem 0.5rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
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
  font-size: 0.72rem;
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--border);
}
.tag--ok {
  color: var(--success);
  border-color: currentColor;
}
.tag--muted {
  color: var(--text-secondary);
}
</style>
