<script setup lang="ts">
// OperationProgress — step indicator + progress bar for one async op.
// Plan 2026-07-09 (U2). Shows the operator what the tool is doing while a
// publish / publish-chain runs in the background: which stage (生成/验证/发布),
// coarse progress %, cancel, and the terminal result or error.
import { computed, ref, watch } from 'vue'
import { cancelOperation, type OperationStatus } from '../api/operations'
import { useOperation } from '../composables/useOperation'
import StatusBadge from './StatusBadge.vue'

const props = defineProps<{
  opId: string
  /** Hide the step list for a compact inline view. */
  compact?: boolean
}>()

const emit = defineEmits<{
  (e: 'settled', op: OperationStatus): void
}>()

const { op } = useOperation(() => props.opId)

const TERMINAL = new Set(['success', 'failed', 'canceled'])

const isTerminal = computed(() => TERMINAL.has(op.value?.status ?? ''))
const isRunning = computed(() => op.value?.running === true && !isTerminal.value)

const currentIndex = computed(() => {
  const stages = op.value?.stages ?? []
  const idx = stages.indexOf(op.value?.stage || '')
  return idx
})

function stepState(i: number): 'done' | 'active' | 'failed' | 'pending' {
  if (isTerminal.value && op.value?.status === 'failed') {
    return i === currentIndex.value ? 'failed' : i < currentIndex.value ? 'done' : 'pending'
  }
  if (isTerminal.value && op.value?.status === 'canceled') {
    return i === currentIndex.value ? 'failed' : i < currentIndex.value ? 'done' : 'pending'
  }
  if (i < currentIndex.value) return 'done'
  if (i === currentIndex.value) return 'active'
  return 'pending'
}

const progressPct = computed(() => Math.round(op.value?.progress_pct ?? 0))

const canceling = ref(false)
async function onCancel(): Promise<void> {
  canceling.value = true
  try {
    await cancelOperation(props.opId)
  } finally {
    canceling.value = false
  }
}

// Emit `settled` exactly once when the op reaches a terminal state, so the
// parent can raise a toast + persist it to notification history.
const emitted = ref(false)
watch(
  () => op.value?.status,
  (status) => {
    if (status && TERMINAL.has(status) && !emitted.value && op.value) {
      emitted.value = true
      emit('settled', op.value)
    }
  },
)
</script>

<template>
  <div v-if="op" class="op-progress" aria-live="polite">
    <div class="d-flex align-items-center justify-content-between mb-2">
      <StatusBadge :status="op.status" />
      <small class="text-muted">{{ op.detail || op.stage || '' }}</small>
      <button
        v-if="isRunning"
        class="btn btn-sm btn-outline-secondary"
        :disabled="canceling"
        @click="onCancel"
      >
        {{ canceling ? '取消中…' : '取消' }}
      </button>
    </div>

    <ol v-if="!compact" class="op-progress__steps list-unstyled d-flex gap-2 mb-2">
      <li
        v-for="(s, i) in op.stages"
        :key="s"
        class="op-step"
        :class="`op-step--${stepState(i)}`"
      >
        <span class="op-step__dot">{{ stepState(i) === 'done' ? '✓' : i + 1 }}</span>
        <span class="op-step__label">{{ s }}</span>
      </li>
    </ol>

    <div class="progress" style="height: 18px">
      <div
        class="progress-bar"
        :class="{ 'progress-bar-striped progress-bar-animated': isRunning }"
        role="progressbar"
        :style="{ width: progressPct + '%' }"
        :aria-valuenow="progressPct"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        {{ progressPct }}%
      </div>
    </div>

    <div v-if="op.status === 'success' && op.result" class="mt-2 small">
      <span class="text-success">✓ 完成</span>
      <span class="ms-2">成功 {{ op.result.n_ok }} 条，失败 {{ op.result.n_failed }} 条</span>
    </div>
    <div v-else-if="op.status === 'failed'" class="mt-2 small text-danger">
      ✗ {{ op.error || '操作失败' }}
    </div>
    <div v-else-if="op.status === 'canceled'" class="mt-2 small text-muted">
        已取消
    </div>
  </div>
  <div v-else class="text-muted small">加载中…</div>
</template>

<style scoped>
.op-step {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-base);
}
.op-step__dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #e9ecef;
  color: #495057;
  font-size: var(--text-xs);
}
.op-step--active .op-step__dot {
  background: var(--primary);
  color: #fff;
}
.op-step--done .op-step__dot {
  background: var(--success);
  color: #fff;
}
.op-step--failed .op-step__dot {
  background: var(--danger);
  color: #fff;
}
.op-step--pending .op-step__label {
  color: #adb5bd;
}
</style>
