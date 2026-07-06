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
import { computed } from 'vue'
import StateBlock from './StateBlock.vue'

const props = withDefaults(
  defineProps<{
    items: T[]
    loading?: boolean
    error?: unknown
    emptyText?: string
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
  }>(),
  { loading: false, emptyText: '暂无数据', selected: () => new Set(), disabled: false },
)

const emit = defineEmits<{
  retry: []
  'update:selected': [Set<string>]
  'update:offset': [number]
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

function toggleAll(): void {
  emit('update:selected', allSelected.value ? new Set() : new Set(props.items.map((r) => r.id)))
}

function toggleRow(id: string): void {
  const next = new Set(props.selected)
  next.has(id) ? next.delete(id) : next.add(id)
  emit('update:selected', next)
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
          <thead>
            <tr>
              <th class="col-select">
                <input
                  type="checkbox"
                  :checked="allSelected"
                  :disabled="disabled"
                  :aria-label="allSelected ? '取消全选' : '全选本页'"
                  @change="toggleAll"
                />
              </th>
              <slot name="head" />
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in items" :key="row.id" :data-id="row.id">
              <td class="col-select">
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
</style>
