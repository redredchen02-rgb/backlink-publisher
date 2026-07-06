<script setup lang="ts">
// Notion channel card (Plan 2026-06-18-002 U8) — migrates the last token-paste
// escape hatch off the legacy settings page into the SPA. Notion's credential is
// two fields (integration_token + database_id) written to a 0600 file via the
// already-migrated POST /api/v1/settings/notion-token. Unlike Blogger's OAuth
// secret, Notion has NO blank-preserve: both fields are required on every save
// (mirrors the legacy form), so the secret is never pre-filled and a blank submit
// is a 422 the user must resolve by re-entering the token. database_id is NOT a
// secret, so it hydrates from the status GET for display/edit.
import { computed, reactive, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { getNotionStatus, saveNotionToken, clearNotionToken } from '../../api/settings'
import StateBlock from '../../components/StateBlock.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useSnapshotDirty } from '../../composables/useSnapshotDirty'
import { useSettingsForm } from '../../composables/useSettingsForm'
import { useNotificationsStore } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const qc = useQueryClient()

// Plan 2026-07-06-005 W1 (D15): edit-surface query (hydrates
// `form.database_id`) — window-focus refetch explicitly OFF. See
// docs/audits/2026-07-06-webui-refresh-inventory.md.
const query = useQuery({
  queryKey: ['settings', 'notion-status'],
  queryFn: getNotionStatus,
  refetchOnWindowFocus: false,
})
const status = computed(() => query.data.value ?? null)
const configured = computed(() => Boolean(status.value?.configured))

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

// integration_token starts blank (never pre-filled); database_id hydrates from
// status (not a secret).
const form = reactive({ integration_token: '', database_id: '' })

// Plan 2026-07-06-005 W2 — hydration-overwrite fix; see BloggerCard's
// identical comment for the full rationale (same shape: a secret field that
// gets programmatically blanked after save, plus a non-secret field hydrated
// from the status query).
const { dirty, markClean } = useSnapshotDirty('settings-notion', 'Notion', () => form)

// Plan 2026-07-06-005 W6 — shared save convention: 422 renders inline (best-
// effort field attribution via regex — see useSettingsForm's docstring),
// success toast + this card's `markClean()`, per-card `saving` busy.
const { saving, formError, fieldErrors, run } = useSettingsForm(markClean, {
  integration_token: /integration[ _]?token/i,
  database_id: /database[ _]?id/i,
})

watch(
  () => status.value,
  (s) => {
    if (!s) return
    if (dirty.value) return
    form.database_id = s.database_id
    markClean()
  },
  { immediate: true },
)

const tokenPlaceholder = computed(() =>
  configured.value ? '已配置（更新需重新填入完整 token）' : 'secret_...',
)

async function onSave(): Promise<void> {
  const result = await run(() => saveNotionToken(form.integration_token, form.database_id), {
    successMessage: 'Notion 凭据已保存',
    onSuccess: () => {
      form.integration_token = ''
    },
  })
  if (result) {
    await qc.invalidateQueries({ queryKey: ['settings', 'notion-status'] })
    await qc.invalidateQueries({ queryKey: ['settings', 'channels'] })
  }
}

async function onClear(): Promise<void> {
  if (!window.confirm('确认清除 Notion 凭据？')) return
  try {
    const r = await clearNotionToken()
    notify.push(r.message || 'Notion 凭据已清除', 'success')
    form.integration_token = ''
    markClean()
    await qc.invalidateQueries({ queryKey: ['settings', 'notion-status'] })
    await qc.invalidateQueries({ queryKey: ['settings', 'channels'] })
  } catch (e) {
    toastError(e)
  }
}
</script>

<template>
  <section class="card" aria-labelledby="notion-h">
    <h2 id="notion-h">Notion</h2>
    <StateBlock :state="state" :error="query.error.value" @retry="query.refetch()">
      <div class="notion__status">
        <span class="tag" :class="configured ? 'tag--ok' : 'tag--err'" data-test="notion-badge">
          {{ configured ? '已配置' : '未配置' }}
        </span>
      </div>

      <p class="muted">
        在 <a href="https://www.notion.so/my-integrations" target="_blank" rel="noopener">
        Notion → My integrations</a> 建 internal integration 取 token，并把目标 database
        分享给该 integration；Database ID 是分享链接里 <code>?v=</code> 前的 32 位 ID。
      </p>

      <form class="notion__form" @submit.prevent="onSave">
        <div class="field">
          <label for="nt-token">Integration Token</label>
          <input
            id="nt-token"
            v-model="form.integration_token"
            type="password"
            spellcheck="false"
            autocomplete="off"
            :placeholder="tokenPlaceholder"
          />
          <small v-if="fieldErrors.integration_token" class="field-error" data-test="err-token">
            {{ fieldErrors.integration_token }}
          </small>
        </div>
        <div class="field">
          <label for="nt-db">Database ID</label>
          <input
            id="nt-db"
            v-model="form.database_id"
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="32 位十六进制 ID"
          />
          <small v-if="fieldErrors.database_id" class="field-error" data-test="err-db">
            {{ fieldErrors.database_id }}
          </small>
        </div>
        <p v-if="formError" class="form-error" data-test="notion-form-error">{{ formError }}</p>
        <div class="notion__actions">
          <button type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '确认绑定' }}
          </button>
          <button v-if="configured" type="button" class="danger" @click="onClear">
            清除
          </button>
        </div>
      </form>
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
.notion__status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.notion__form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.field input {
  padding: var(--control-pad-y) var(--control-pad-x);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-base);
}
.notion__actions {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
  align-items: center;
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
.tag--err {
  color: var(--danger);
  border-color: currentColor;
}
.field-error,
.form-error {
  color: var(--danger);
  font-size: var(--text-sm);
  margin: 0.25rem 0 0;
}
</style>
