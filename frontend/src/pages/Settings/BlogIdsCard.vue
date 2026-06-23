<script setup lang="ts">
// Blogger Blog ID mapping editor (Plan 2026-06-18-002 U7, settings section 3 slice
// 6 — channel section finale). Edits the domain → Blogger Blog ID routing map
// consulted at publish time. Dynamic add/remove rows; the server strips, drops
// blank pairs and dedups by domain, so the client just sends what's typed.
import { computed, reactive, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { getBlogIds, saveBlogIds } from '../../api/settings'
import { classifyError } from '../../lib/errors'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore } from '../../stores/notifications'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

interface Row {
  domain: string
  blog_id: string
}

const notify = useNotificationsStore()
const qc = useQueryClient()

const query = useQuery({ queryKey: ['settings', 'blog-ids'], queryFn: getBlogIds })

// Editable rows, kept local so edits don't fight the cached server state. Always
// keep at least one (blank) row so the operator has somewhere to type.
const rows = reactive<Row[]>([])
const saving = ref(false)

watch(
  () => query.data.value,
  (data) => {
    if (!data) return
    rows.splice(0, rows.length)
    for (const [domain, blog_id] of Object.entries(data.blog_ids)) {
      rows.push({ domain, blog_id })
    }
    if (rows.length === 0) rows.push({ domain: '', blog_id: '' })
  },
  { immediate: true },
)

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

function addRow(): void {
  rows.push({ domain: '', blog_id: '' })
}

function removeRow(i: number): void {
  rows.splice(i, 1)
  if (rows.length === 0) rows.push({ domain: '', blog_id: '' })
}

async function onSave(): Promise<void> {
  if (saving.value) return
  saving.value = true
  try {
    const mapping: Record<string, string> = {}
    for (const r of rows) {
      const d = r.domain.trim()
      const b = r.blog_id.trim()
      if (d && b) mapping[d] = b
    }
    const r = await saveBlogIds(mapping)
    notify.push(r.message || 'Blog ID 映射已保存', 'success')
    await qc.invalidateQueries({ queryKey: ['settings', 'blog-ids'] })
  } catch (e) {
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="card" aria-labelledby="blogids-h">
    <h2 id="blogids-h">Blogger Blog ID 映射</h2>
    <p class="muted">
      将每个目标主域名映射到对应的 Blogger Blog ID（在 Blogger 控制台 URL
      <code>blogger.com/blog/posts/<strong>1234567890</strong></code> 中可见）。
    </p>
    <StateBlock :state="state" :error="query.error.value" @retry="query.refetch()">
      <form @submit.prevent="onSave">
        <div v-for="(row, i) in rows" :key="i" class="row" data-test="blogid-row">
          <input
            v-model="row.domain"
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="https://your-site.com"
            aria-label="目标域名"
          />
          <input
            v-model="row.blog_id"
            type="text"
            spellcheck="false"
            autocomplete="off"
            placeholder="1234567890123456789"
            aria-label="Blog ID"
          />
          <button type="button" class="danger" aria-label="删除此行" @click="removeRow(i)">
            ✕
          </button>
        </div>
        <div class="actions">
          <button type="button" class="secondary" @click="addRow">新增一行</button>
          <button type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '保存映射' }}
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
  border-radius: 10px;
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
.row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.row input {
  padding: 0.4rem 0.5rem;
  font-size: var(--text-base);
}
.row input:first-child {
  flex: 2;
}
.row input:nth-child(2) {
  flex: 1;
  font-family: var(--font-mono, monospace);
}
.actions {
  display: flex;
  gap: 0.6rem;
  margin-top: 0.75rem;
}
.secondary {
  background: transparent;
}
.danger {
  color: var(--danger);
  border-color: currentColor;
  background: transparent;
  padding: 0 0.6rem;
}
</style>
