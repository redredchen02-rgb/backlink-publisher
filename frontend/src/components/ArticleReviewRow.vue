<script setup lang="ts">
import { ref, watch } from 'vue'
import type { PlanRow } from '../api/pipeline'
import type { PlanRowPatch } from '../stores/publish'

const props = defineProps<{
  row: PlanRow
  patch: PlanRowPatch
}>()

const emit = defineEmits<{
  patch: [PlanRowPatch]
}>()

function field(row: PlanRow, key: string): string {
  const v = row[key]
  return typeof v === 'string' ? v : ''
}

function rowAnchors(row: PlanRow): string[] {
  const v = row['anchors']
  if (typeof v === 'string') return v.split('\n').filter(Boolean)
  if (Array.isArray(v)) return (v as unknown[]).filter((a): a is string => typeof a === 'string')
  return []
}

const originalTitle = field(props.row, 'custom_title') || field(props.row, 'title')
const localTitle = ref('')
const localBody = ref('')

watch(
  () => props.patch,
  (p) => {
    localTitle.value = p.custom_title ?? originalTitle
    localBody.value = p.content_markdown ?? field(props.row, 'content_markdown')
  },
  { immediate: true },
)

function emitPatch(): void {
  emit('patch', { custom_title: localTitle.value, content_markdown: localBody.value })
}
</script>

<template>
  <details class="review-row">
    <summary class="review-row__summary">
      {{ localTitle || '(無標題)' }}
      <span v-if="localTitle !== originalTitle" class="review-row__edited" aria-label="已修改">*</span>
    </summary>
    <div class="review-row__body">
      <label class="review-row__label">
        標題
        <input
          v-model="localTitle"
          class="review-row__input"
          type="text"
          @blur="emitPatch"
        />
      </label>
      <label class="review-row__label">
        正文
        <textarea
          v-model="localBody"
          class="review-row__textarea"
          rows="8"
          @blur="emitPatch"
        />
      </label>
      <div v-if="field(row, 'target_url')" class="review-row__field">
        <span class="review-row__field-label">目標 URL</span>
        <span>{{ field(row, 'target_url') }}</span>
      </div>
      <div v-if="rowAnchors(row).length" class="review-row__field">
        <span class="review-row__field-label">錨文字</span>
        <ul class="review-row__anchors">
          <li v-for="(a, i) in rowAnchors(row)" :key="i">{{ a }}</li>
        </ul>
      </div>
    </div>
  </details>
</template>

<style scoped>
.review-row {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0.5rem 0.75rem;
}
.review-row__summary {
  cursor: pointer;
  font-weight: 500;
  user-select: none;
  list-style: none;
}
.review-row__summary::-webkit-details-marker {
  display: none;
}
.review-row__summary::before {
  content: '▶';
  display: inline-block;
  margin-right: 0.4rem;
  font-size: 0.7em;
  transition: transform 0.15s;
}
details[open] .review-row__summary::before {
  transform: rotate(90deg);
}
.review-row__edited {
  color: var(--primary);
  margin-left: 0.25rem;
}
.review-row__body {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-top: 0.75rem;
}
.review-row__label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--text-sm, 0.875rem);
  color: var(--text-secondary);
}
.review-row__input,
.review-row__textarea {
  font: inherit;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.6rem;
  background: var(--surface-raised);
  color: var(--text);
  width: 100%;
  box-sizing: border-box;
}
.review-row__textarea {
  resize: vertical;
}
.review-row__field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: var(--text-sm, 0.875rem);
}
.review-row__field-label {
  color: var(--text-secondary);
}
.review-row__anchors {
  margin: 0;
  padding-left: 1.1rem;
}
</style>
