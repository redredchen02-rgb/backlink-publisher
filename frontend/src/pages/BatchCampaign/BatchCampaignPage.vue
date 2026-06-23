<script setup lang="ts">
// Batch-campaign creation page — Plan 2026-06-18-002 U7 (batch_campaign page).
//
// Replaces the legacy Jinja /batch-campaign form. Upload seeds (newline JSONL,
// ≤10, each needs seed_text), pick platforms (connected ones from the
// connection-state partition, falling back to the flat list), choose mode
// (draft/publish), optional cap + seed-delay. Submit → POST /api/v1/campaigns;
// a 422 carries field-level errors[] (rendered inline), success returns a
// campaign_id and we navigate OUT to the legacy /campaign/<id> progress page
// (dual-stack: that progress view is a separate, not-yet-migrated route).
import { computed, reactive, ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  createCampaign,
  getCampaignForm,
  type PartitionMainRow,
} from '../../api/campaigns'
import { ApiError } from '../../api/client'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { classifyError } from '../../lib/errors'

const notify = useNotificationsStore()
const formQuery = useQuery({ queryKey: ['campaigns', 'form'], queryFn: getCampaignForm })

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (formQuery.isPending.value) return 'loading'
  if (formQuery.isError.value) return 'error'
  return 'ready'
})

// Selectable platforms: partition.main (connected) if available, else the flat list.
const selectable = computed<{ name: string; needsReconnect: boolean }[]>(() => {
  const data = formQuery.data.value
  if (!data) return []
  const partition = data.publish_partition
  if (partition?.main?.length) {
    return partition.main.map((row: PartitionMainRow) => ({
      name: row[0],
      needsReconnect: Boolean(row[2]),
    }))
  }
  return data.platforms.map((name) => ({ name, needsReconnect: false }))
})
const extensionCount = computed(() => formQuery.data.value?.publish_partition?.extension_count ?? 0)

const form = reactive({ seeds: '', mode: 'draft', cap: '', seed_delay: '0' })
const selected = ref<Set<string>>(new Set())
const fieldErrors = reactive<Record<string, string>>({})
const submitting = ref(false)

function togglePlatform(name: string): void {
  const next = new Set(selected.value)
  next.has(name) ? next.delete(name) : next.add(name)
  selected.value = next
}

function clearErrors(): void {
  for (const k of Object.keys(fieldErrors)) delete fieldErrors[k]
}

async function onSubmit(): Promise<void> {
  if (submitting.value) return
  submitting.value = true
  clearErrors()
  try {
    const r = await createCampaign({
      seeds: form.seeds,
      platforms: [...selected.value],
      mode: form.mode,
      cap: form.cap,
      seed_delay: form.seed_delay,
    })
    // Leave the SPA for the legacy progress page (not yet migrated).
    window.location.href = `/campaign/${r.campaign_id}`
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) {
      const errs = (e.payload as { errors?: { field: string; message: string }[] })?.errors ?? []
      for (const { field, message } of errs) fieldErrors[field] = message
      if (errs.length) {
        submitting.value = false
        return
      }
    }
    const c = classifyError(e)
    notify.push(`${c.title}：${c.message}`, 'error')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="campaign">
    <h1>批量发布活动</h1>
    <StateBlock :state="blockState" :error="formQuery.error.value" @retry="formQuery.refetch()">
      <form class="campaign-form" novalidate @submit.prevent="onSubmit">
        <label>
          seeds（每行一条 JSON，最多 10 条，每条需含 <code>seed_text</code>）
          <textarea v-model="form.seeds" rows="6" placeholder='{"seed_text": "..."}' />
          <span v-if="fieldErrors.seeds" class="field-error">{{ fieldErrors.seeds }}</span>
        </label>

        <fieldset>
          <legend>平台</legend>
          <label v-for="p in selectable" :key="p.name" class="platform">
            <input
              type="checkbox"
              :checked="selected.has(p.name)"
              :disabled="p.needsReconnect"
              @change="togglePlatform(p.name)"
            />
            {{ p.name }}
            <span v-if="p.needsReconnect" class="muted">（需重新串接）</span>
          </label>
          <p v-if="extensionCount" class="muted">拓展区 {{ extensionCount }} 个未串接平台已隐藏</p>
          <span v-if="fieldErrors.platforms" class="field-error">{{ fieldErrors.platforms }}</span>
        </fieldset>

        <fieldset>
          <legend>参数</legend>
          <div class="mode-toggle" role="radiogroup" aria-label="模式">
            <label><input v-model="form.mode" type="radio" value="draft" /> 草稿</label>
            <label><input v-model="form.mode" type="radio" value="publish" /> 发布</label>
          </div>
          <span v-if="fieldErrors.mode" class="field-error">{{ fieldErrors.mode }}</span>
          <div class="two-col">
            <label>
              上限 cap（可选）
              <input v-model="form.cap" type="number" min="1" />
              <span v-if="fieldErrors.cap" class="field-error">{{ fieldErrors.cap }}</span>
            </label>
            <label>
              seed 延迟（秒）
              <input v-model="form.seed_delay" type="number" min="0" />
              <span v-if="fieldErrors.seed_delay" class="field-error">{{ fieldErrors.seed_delay }}</span>
            </label>
          </div>
        </fieldset>

        <div class="actions">
          <button type="submit" class="primary" :disabled="submitting">创建活动</button>
        </div>
      </form>
    </StateBlock>
  </section>
</template>

<style scoped>
.campaign {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.campaign-form {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}
fieldset {
  border: 1px solid var(--border, #30363d);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
legend {
  font-weight: 600;
  padding: 0 0.4rem;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.9rem;
}
label.platform {
  flex-direction: row;
  align-items: center;
  gap: 0.4rem;
}
.mode-toggle {
  display: flex;
  gap: 1rem;
}
.mode-toggle label {
  flex-direction: row;
  align-items: center;
  gap: 0.3rem;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}
textarea,
input[type='number'] {
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--border, #30363d);
  border-radius: 6px;
  background: var(--surface-raised, #161b22);
  color: inherit;
  font: inherit;
}
.field-error {
  color: var(--danger, #f85149);
  font-size: 0.8rem;
}
.muted {
  color: var(--text-secondary, #8b949e);
  font-size: 0.85rem;
}
button.primary {
  background: var(--primary, #58a6ff);
  color: #0d1117;
  border: none;
  border-radius: 6px;
  padding: 0.45rem 1rem;
  font-weight: 600;
  cursor: pointer;
}
</style>
