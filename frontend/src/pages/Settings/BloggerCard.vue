<script setup lang="ts">
// Blogger channel card (Plan 2026-06-18-002 U7, settings section 3 slice 5) — the
// OAuth credential half. "确认绑定" saves Client ID/Secret via the migrated JSON
// endpoint (stays in the SPA); "使用 Google 帐号登入" submits a real form to the
// LEGACY /settings/blogger/oauth-start route — the OAuth consent handshake is a
// full-page browser navigation (Google's redirect + the oauth-callback landing
// cannot be JSON), so it stays legacy by design. Revoke deletes the token file.
//
// The Blog ID → Blogger Blog ID mapping editor lands in the next slice.
import { computed, reactive, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  getBloggerStatus,
  saveBloggerOauth,
  revokeBlogger,
} from '../../api/settings'
import { csrfToken } from '../../api/client'
import StateBlock from '../../components/StateBlock.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { useErrorToast } from '../../composables/useErrorToast'
import { useSnapshotDirty } from '../../composables/useSnapshotDirty'
import { useSettingsForm } from '../../composables/useSettingsForm'
import { useNotificationsStore } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const { toastError } = useErrorToast()
const qc = useQueryClient()

// Plan 2026-07-06-005 W1 (D15): edit-surface query (hydrates `form.client_id`)
// — window-focus refetch explicitly OFF. See
// docs/audits/2026-07-06-webui-refresh-inventory.md.
const query = useQuery({
  queryKey: ['settings', 'blogger-status'],
  queryFn: getBloggerStatus,
  refetchOnWindowFocus: false,
})
const status = computed(() => query.data.value ?? null)
const authorized = computed(() => Boolean(status.value?.authorized))

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

// Editable creds. client_secret starts blank (never pre-filled); a blank submit
// preserves the stored secret. client_id hydrates from status (it's not a secret).
const form = reactive({ client_id: '', client_secret: '' })

// Plan 2026-07-06-005 W2 — hydration-overwrite fix: while the operator has
// unsaved edits (client_id and/or client_secret typed but not yet saved), a
// query refetch must not clobber them. `markClean()` re-baselines right after
// a hydration actually runs, including the one echoing this card's own
// successful save (where `client_secret` gets programmatically blanked).
const { dirty, markClean } = useSnapshotDirty('settings-blogger', 'Blogger', () => form)

// Plan 2026-07-06-005 W6 — shared save convention: 422 renders inline, keyed
// to the field the backend's detail text names (best-effort regex match —
// see useSettingsForm's module docstring for why a freeform `detail` string
// can only be attributed heuristically), success toast + this card's
// `markClean()`, per-card `saving` busy.
const { saving, formError, fieldErrors, run } = useSettingsForm(markClean, {
  client_secret: /client[ _]?secret/i,
  client_id: /client[ _]?id/i,
})

watch(
  () => status.value,
  (s) => {
    if (!s) return
    if (dirty.value) return
    form.client_id = s.client_id
    markClean()
  },
  { immediate: true },
)

const secretPlaceholder = computed(() =>
  status.value?.client_secret_set ? '已设置（留空保留现值）' : 'GOCSPX-...',
)

async function onSave(): Promise<void> {
  const result = await run(() => saveBloggerOauth(form.client_id, form.client_secret), {
    successMessage: '凭据已确认绑定',
    onSuccess: () => {
      form.client_secret = ''
    },
  })
  if (result) await qc.invalidateQueries({ queryKey: ['settings', 'blogger-status'] })
}

// Google login: the consent handshake is a full-page POST to the legacy
// oauth-start route (it saves the creds, then 302s to Google). Build a real form
// (createElement, never innerHTML) carrying the CSRF token + creds and submit it.
async function onGoogleLogin(): Promise<void> {
  const token = await csrfToken()
  const f = document.createElement('form')
  f.method = 'POST'
  f.action = '/settings/blogger/oauth-start'
  const add = (name: string, value: string) => {
    const i = document.createElement('input')
    i.type = 'hidden'
    i.name = name
    i.value = value
    f.appendChild(i)
  }
  add('csrf_token', token)
  add('client_id', form.client_id)
  add('client_secret', form.client_secret)
  document.body.appendChild(f)
  f.submit()
}

// Revoke — native window.confirm migrated to the shared ConfirmDialog (W3).
// Same confirm semantics: confirm → revoke, cancel → no-op. Errors keep going
// to the error toast (not the dialog's inline error) so the pre-W3 behavior of
// "dialog gone, toast shown" is preserved — doRevoke therefore never rejects.
const revokeOpen = ref(false)

function onRevoke(): void {
  revokeOpen.value = true
}

async function doRevoke(): Promise<void> {
  try {
    const r = await revokeBlogger()
    notify.push(r.message || 'Blogger 授权已撤销', 'success')
    await qc.invalidateQueries({ queryKey: ['settings', 'blogger-status'] })
  } catch (e) {
    toastError(e)
  }
}
</script>

<template>
  <section class="card" aria-labelledby="blogger-h">
    <h2 id="blogger-h">Blogger</h2>
    <StateBlock :state="state" :error="query.error.value" @retry="query.refetch()">
      <div class="blogger__status">
        <span class="tag" :class="authorized ? 'tag--ok' : 'tag--err'" data-test="blogger-badge">
          {{ authorized ? '已授权' : '未授权' }}
        </span>
        <small v-if="status?.client_id" class="muted">已绑定凭据</small>
      </div>

      <p class="muted">
        Step 1 — 在 <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener">
        Google Cloud Console</a> 注册回调网址（Web 应用类型需完整网址；桌面应用只需
        <code>http://localhost</code>）：
      </p>
      <code class="blogger__cb">{{ status?.callback_uri }}</code>

      <form class="blogger__form" @submit.prevent="onSave">
        <p class="muted">Step 2 — 填入 OAuth 凭据</p>
        <div class="field">
          <label for="bg-cid">Client ID</label>
          <input
            id="bg-cid"
            v-model="form.client_id"
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="xxxx.apps.googleusercontent.com"
          />
          <small v-if="fieldErrors.client_id" class="field-error" data-test="err-client-id">
            {{ fieldErrors.client_id }}
          </small>
        </div>
        <div class="field">
          <label for="bg-secret">Client Secret</label>
          <input
            id="bg-secret"
            v-model="form.client_secret"
            type="password"
            spellcheck="false"
            autocomplete="off"
            :placeholder="secretPlaceholder"
          />
          <small v-if="fieldErrors.client_secret" class="field-error" data-test="err-client-secret">
            {{ fieldErrors.client_secret }}
          </small>
        </div>
        <p v-if="formError" class="form-error" data-test="blogger-form-error">{{ formError }}</p>
        <div class="blogger__actions">
          <button type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '确认绑定' }}
          </button>
          <button type="button" class="google" @click="onGoogleLogin">使用 Google 帐号登入</button>
          <button v-if="authorized" type="button" class="danger" @click="onRevoke">
            撤销授权
          </button>
        </div>
        <small class="muted">
          「确认绑定」只保存凭据；「使用 Google 帐号登入」保存后立即跳转 Google 授权。
        </small>
      </form>
    </StateBlock>

    <ConfirmDialog
      v-model:open="revokeOpen"
      danger
      title="撤销 Blogger 授权"
      confirm-label="确认撤销"
      :confirm="doRevoke"
    >
      <p>确认撤销 Blogger 授权？下次发布前需重新登入。</p>
    </ConfirmDialog>
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
.blogger__status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.blogger__cb {
  display: block;
  margin: 0.3rem 0 0.85rem;
  padding: 0.35rem 0.5rem;
  background: var(--surface-base);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  word-break: break-all;
}
.blogger__form {
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
.blogger__actions {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
  align-items: center;
}
.google {
  color: var(--primary);
  border-color: currentColor;
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
