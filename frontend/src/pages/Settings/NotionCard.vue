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
import { ApiError } from '../../api/client'
import { classifyError } from '../../lib/errors'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const notify = useNotificationsStore()
const qc = useQueryClient()

const query = useQuery({ queryKey: ['settings', 'notion-status'], queryFn: getNotionStatus })
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
const saving = ref(false)

watch(
  () => status.value,
  (s) => {
    if (s) form.database_id = s.database_id
  },
  { immediate: true },
)

const tokenPlaceholder = computed(() =>
  configured.value ? '已配置（更新需重新填入完整 token）' : 'secret_...',
)

async function onSave(): Promise<void> {
  if (saving.value) return
  saving.value = true
  try {
    const r = await saveNotionToken(form.integration_token, form.database_id)
    notify.push(r.message || 'Notion 凭据已保存', 'success')
    form.integration_token = ''
    await qc.invalidateQueries({ queryKey: ['settings', 'notion-status'] })
    await qc.invalidateQueries({ queryKey: ['settings', 'channels'] })
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const detail = (e.payload as { detail?: string })?.detail
      notify.push(detail || '请填写 Integration Token 和 Database ID', 'warning')
      return
    }
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  } finally {
    saving.value = false
  }
}

async function onClear(): Promise<void> {
  if (!window.confirm('确认清除 Notion 凭据？')) return
  try {
    const r = await clearNotionToken()
    notify.push(r.message || 'Notion 凭据已清除', 'success')
    form.integration_token = ''
    await qc.invalidateQueries({ queryKey: ['settings', 'notion-status'] })
    await qc.invalidateQueries({ queryKey: ['settings', 'channels'] })
  } catch (e) {
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
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
        </div>
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
  background: var(--surface-raised, #161b22);
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
  padding: 0.4rem 0.5rem;
  font-family: var(--font-mono, monospace);
  font-size: 0.85rem;
}
.notion__actions {
  display: flex;
  gap: 0.6rem;
  flex-wrap: wrap;
  align-items: center;
}
.danger {
  color: var(--danger, #f85149);
  border-color: currentColor;
  background: transparent;
}
.tag {
  font-size: 0.72rem;
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--border, #30363d);
}
.tag--ok {
  color: var(--success, #3fb950);
  border-color: currentColor;
}
.tag--err {
  color: var(--danger, #f85149);
  border-color: currentColor;
}
</style>
