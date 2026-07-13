<script setup lang="ts" generic="T extends { id: string }">
// Shared list-view component — Plan 2026-07-02-001 U5.
//
// Covers only the capabilities every adopting page already hand-rolled:
// render / empty-state (via StateBlock) / row selection / pagination hookup.
// Sorting is explicitly out of scope (Scope Boundaries) -- column content is
// fully caller-controlled via the `head`/`row` slots, so this stays a thin
// wrapper rather than a column-definition-driven grid.
//
// `id` must be a stable, unique string per row -- it backs :key, the
// checkbox aria-label, and membership in the `selected` Set.
import { computed, ref } from 'vue'
import StateBlock from './StateBlock.vue'

const props = withDefaults(
  defineProps<{
    items: T[]
    loading?: boolean
    error?: unknown
    emptyText?: string
    /** Accessible caption for the <table> (W11). */
    caption?: string
    selected?: Set<string>
    /** Present together to opt into the pagination footer (K6, opt-in). */
    total?: number
    limit?: number
    offset?: number
    /**
     * Disables selection checkboxes and pager buttons while a mutation is in
     * flight. Without this, paging away mid-mutation lets the mutation's
     * post-action refetch/clamp resolve against the offset the user has since
     * navigated to instead of the one the mutation actually ran against
     * (code review finding, U5).
     */
    disabled?: boolean
    /**
     * Optional per-row class map, keyed by the row itself (Plan
     * 2026-07-06-reintegrate-u5 W5/W10 reintegration) -- lets a caller mark
     * an individual `<tr>` (e.g. a soft-deleted row pending undo, or a row
     * highlighted via a cross-page deep-link) without DataTable needing to
     * know anything about *why*. Optional/undefined is a pure no-op, so
     * existing callers (Drafts, etc.) are unaffected.
     */
    rowClass?: (row: T) => Record<string, boolean>
    /** Enable keyboard row navigation (Up/Down arrows, W11). */
    rowKeyboardNav?: boolean
    /** Opt-in row-selection checkbox column. Off by default: most list pages are read-only. */
    selectable?: boolean
  }>(),
  { loading: false, emptyText: '暂无数据', caption: '', selected: () => new Set(), disabled: false, rowKeyboardNav: false, selectable: false },
)

const emit = defineEmits<{
  retry: []
  'update:selected': [Set<string>]
  'update:offset': [number]
  /** Enter pressed on a keyboard-focused row (W11) -- caller decides the row's "main action". */
  rowActivate: [T]
}>()

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (props.loading) return 'loading'
  if (props.error) return 'error'
  // Empty-table state routes through StateBlock's own empty treatment,
  // never a bare <table> with a zero-row <tbody> (explicit test scenario).
  return props.items.length ? 'ready' : 'empty'
})

const allSelected = computed(
  () => props.items.length > 0 && props.items.every((row) => props.selected.has(row.id)),
)
const someSelected = computed(
  () => props.items.some((row) => props.selected.has(row.id)) && !allSelected.value,
)

function toggleAll(): void {
  emit('update:selected', allSelected.value ? new Set() : new Set(props.items.map((r) => r.id)))
}

function toggleRow(id: string): void {
  const next = new Set(props.selected)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  emit('update:selected', next)
}

// -1 = "no row explicitly focused yet" -- falls back to row 0 as the roving
// tabindex target so the table is Tab-reachable at all before any arrow-key
// interaction (fixing a draft bug where every row started at tabindex="-1").
const focusedRowIndex = ref(-1)
const activeRowIndex = computed(() => (focusedRowIndex.value >= 0 ? focusedRowIndex.value : 0))
const tbodyRef = ref<HTMLElement | null>(null)

function onRowKeydown(event: KeyboardEvent, index: number): void {
  if (!props.rowKeyboardNav || props.disabled) return
  // Only handle the key when the <tr> itself is focused -- not when it
  // bubbled up from a nested interactive control (checkbox/link/button/
  // datetime input), which must keep its own native key handling untouched.
  if (event.target !== event.currentTarget) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    const next = Math.min(index + 1, props.items.length - 1)
    _focusRow(next)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    const prev = Math.max(index - 1, 0)
    _focusRow(prev)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const row = props.items[index]
    if (row) emit('rowActivate', row)
  }
}

function onRowClick(event: MouseEvent, row: T): void {
  if (!props.rowKeyboardNav || props.disabled) return
  const target = event.target as HTMLElement | null
  if (target?.closest('a, button, input, select, textarea, label')) return
  emit('rowActivate', row)
}

function _focusRow(index: number): void {
  focusedRowIndex.value = index
  const rows = tbodyRef.value?.querySelectorAll('tr')
  if (rows && rows[index]) {
    ;(rows[index] as HTMLElement).focus()
  }
}

// Keeps the roving-tabindex target in sync when a row is focused by means
// other than the arrow keys (mouse click, or Tab landing on row 0).
function onRowFocus(index: number): void {
  if (!props.rowKeyboardNav) return
  focusedRowIndex.value = index
}

const paginated = computed(() => props.limit != null && props.total != null)
const safeLimit = computed(() => props.limit || 1)
const currentOffset = computed(() => props.offset ?? 0)
const currentPage = computed(() => Math.floor(currentOffset.value / safeLimit.value) + 1)
const pageCount = computed(() => Math.max(1, Math.ceil((props.total ?? 0) / safeLimit.value)))
const hasPrev = computed(() => currentOffset.value > 0)
const hasNext = computed(() => currentOffset.value + safeLimit.value < (props.total ?? 0))

// Design decision (plan's own explicit requirement): changing page clears the
// selection -- a selection made on page 1 must never silently act on page 2's
// rows once the offset changes. The bulk-action count badge (owned by the
// caller, reading selected.size) then naturally reflects only the current page.
function goToOffset(next: number): void {
  emit('update:selected', new Set())
  emit('update:offset', Math.max(0, next))
}
const goPrev = () => hasPrev.value && goToOffset(currentOffset.value - safeLimit.value)
const goNext = () => hasNext.value && goToOffset(currentOffset.value + safeLimit.value)
</script>

<template>
  <div class="data-table-component">
    <StateBlock :state="blockState" :error="error" :empty-text="emptyText" @retry="emit('retry')">
      <div class="data-table-wrap">
        <table class="data-table">
          <caption v-if="caption" class="sr-only">{{ caption }}</caption>
          <thead>
            <tr>
              <th v-if="selectable" class="col-select" scope="col">
                <input
                  type="checkbox"
                  :checked="allSelected"
                  :indeterminate="someSelected"
                  :disabled="disabled"
                  :aria-label="allSelected ? '取消全选' : someSelected ? '部分选中' : '全选本页'"
                  @change="toggleAll"
                />
              </th>
              <slot name="head" />
            </tr>
          </thead>
          <tbody ref="tbodyRef">
            <tr
              v-for="(row, index) in items"
              :key="row.id"
              :data-id="row.id"
              :class="rowClass ? rowClass(row) : undefined"
              :tabindex="rowKeyboardNav && !disabled ? (activeRowIndex === index ? 0 : -1) : undefined"
              @keydown="onRowKeydown($event, index)"
              @focus="onRowFocus(index)"
              @click="onRowClick($event, row)"
            >
              <td v-if="selectable" class="col-select">
                <input
                  type="checkbox"
                  :checked="selected.has(row.id)"
                  :disabled="disabled"
                  :aria-label="`选择 ${row.id}`"
                  @change="toggleRow(row.id)"
                />
              </td>
              <slot name="row" :row="row" />
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="paginated" class="data-table__pager">
        <button type="button" :disabled="!hasPrev || disabled" @click="goPrev">上一页</button>
        <span class="muted">第 {{ currentPage }} / {{ pageCount }} 页 · 共 {{ total }} 条</span>
        <button type="button" :disabled="!hasNext || disabled" @click="goNext">下一页</button>
      </div>
    </StateBlock>
  </div>
</template>

<style scoped>
.data-table__pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.75rem 0;
}
.col-select {
  width: 2rem;
  text-align: center;
}
/* Visible roving-tabindex focus ring (W11) -- rows are only ever tabbable
   via tabindex when rowKeyboardNav is on, so this never fires otherwise. */
.data-table tbody tr:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
