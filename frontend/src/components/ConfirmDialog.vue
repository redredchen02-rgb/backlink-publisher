<script setup lang="ts">
// ConfirmDialog — 共享 modal 确认组件(Plan 2026-07-06-005 W3,R3)。
// 取代三种 ad-hoc 确认:KeepAlivePage 自制 ka__confirm-overlay、Settings 卡片的
// window.confirm、以及未来任何新写的一次性确认 UI。
//
// ── 破坏性操作分级(Key Decision D3)────────────────────────────────────────
// * 不可逆操作(硬删除、purge、soft-delete 逾时后的删除、重新发布等无法撤销的
//   动作):必须走本 dialog 二次确认,且 confirm-label 必须明示受影响笔数,
//   例如「确认删除（3 条）」;同时设置 `danger` 变体。
// * 可逆操作(undo 窗口内的 soft-delete 等,W5 落地):免确认直接执行 + undo
//   toast,**不要**使用本 dialog——既 confirm 又 undo 是双重摩擦(D3 明文)。
//
// ── API ─────────────────────────────────────────────────────────────────────
// * `open`(受控)+ `update:open` / `cancel` 事件;标题走 `title` prop 或
//   #title slot,内文走 default slot。
// * `confirm?: () => unknown | Promise<unknown>` — async confirm 模式:等待期间
//   确认钮 busy 且防双击(同步置位,连点只触发一次);resolve → 发出
//   `update:open(false)` 关闭;reject → dialog 保持开启、显示 inline 错误、
//   按钮恢复可用(绝不静默关闭)。
// * 未传 `confirm` 时点击确认只发出 `confirm` 事件,开合完全由父层驱动——
//   KeepAlive 7 态机即受控用法:`open` 由 `actionState === 'confirming'` 派生,
//   confirm 回调自行推进状态机(状态离开 confirming 即关闭 dialog)。
//
// ── a11y ────────────────────────────────────────────────────────────────────
// * role="dialog" + aria-modal + aria-labelledby(标题 id 自动生成)。
// * 开启时 focus 进入首个可聚焦元素,Tab/Shift+Tab 被困在 dialog 内(手法沿用
//   useSidenavDrawer.ts),关闭时 focus 回到触发前元素。
// * 内文区 aria-live="polite":多步骤用例内容切换时向屏幕阅读器播报。
// * Escape 关闭。监听挂在 document 的 **capture 阶段**并 stopPropagation:
//   与 sidenav drawer(bubble 阶段监听)并存时,最上层的 dialog 先关,
//   drawer 不会被同一次按键连带关闭。busy 期间 Escape 无效(防状态分叉)。
// * backdrop 点击不关闭——破坏性确认要求显式取消(Escape 或取消按钮)。
import { computed, onUnmounted, ref, nextTick, useId, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    /** 受控开关。父层经 v-model:open 或 :open + @cancel 驱动。 */
    open: boolean
    /** 标题文本;需要富内容时用 #title slot 覆盖。 */
    title?: string
    /** 确认钮文案。不可逆操作必须含笔数,如「确认删除（3 条）」(D3)。 */
    confirmLabel?: string
    cancelLabel?: string
    /** 不可逆/破坏性操作变体(红色确认钮)。 */
    danger?: boolean
    /**
     * async confirm 回调。等待期间确认钮 busy;resolve 关闭 dialog,
     * reject 保持开启并显示 inline 错误。未传时只 emit('confirm')。
     */
    confirm?: () => unknown | Promise<unknown>
  }>(),
  {
    title: '',
    confirmLabel: '确认',
    cancelLabel: '取消',
    danger: false,
    confirm: undefined,
  },
)

const emit = defineEmits<{
  'update:open': [value: boolean]
  /** 用户显式取消(取消按钮 / Escape)。确认成功关闭不发 cancel。 */
  cancel: []
  /** 仅在未传 confirm prop 时,点击确认钮发出。 */
  confirm: []
}>()

// 标题 id — aria-labelledby 目标,useId() 保证每实例唯一。
const titleId = `confirm-dialog-title-${useId()}`

const busy = ref(false)
const errorMessage = ref('')
const dialogEl = ref<HTMLElement | null>(null)

const confirmClass = computed(() => [
  'cdlg__btn',
  'cdlg__confirm',
  props.danger ? 'cdlg__confirm--danger' : 'cdlg__confirm--primary',
])

// ── Focus trap(手法沿用 useSidenavDrawer.ts)─────────────────────────────
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function getFocusable(): HTMLElement[] {
  if (!dialogEl.value) return []
  return Array.from(dialogEl.value.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
}

function trapTab(e: KeyboardEvent) {
  const focusable = getFocusable()
  if (focusable.length === 0) {
    e.preventDefault()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement as HTMLElement | null
  const activeInDialog = active != null && focusable.includes(active)

  if (e.shiftKey) {
    if (!activeInDialog || active === first) {
      e.preventDefault()
      last.focus()
    }
  } else {
    if (!activeInDialog || active === last) {
      e.preventDefault()
      first.focus()
    }
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    // capture 阶段拦截:下层的 drawer(document bubble 监听)在同一次按键
    // 不会收到 Escape——最上层先关(W3 Escape 分派约束)。
    e.stopPropagation()
    if (!busy.value) requestCancel()
    return
  }
  if (e.key === 'Tab') {
    trapTab(e)
  }
}

// ── 开合生命周期:scroll lock + focus 进出 ──────────────────────────────────
let keydownListener: ((e: KeyboardEvent) => void) | null = null
let prevFocusEl: HTMLElement | null = null
let prevBodyOverflow = ''

function onOpen() {
  busy.value = false
  errorMessage.value = ''
  prevFocusEl = document.activeElement instanceof HTMLElement ? document.activeElement : null
  // 记录并恢复原值(而非清空):drawer 已锁 scroll 时,dialog 关闭不解 drawer 的锁。
  prevBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  keydownListener = handleKeydown
  document.addEventListener('keydown', keydownListener, true)
  nextTick(() => {
    const focusable = getFocusable()
    const target = focusable[0] ?? dialogEl.value
    target?.focus()
  })
}

function onClose() {
  document.body.style.overflow = prevBodyOverflow
  if (keydownListener) {
    document.removeEventListener('keydown', keydownListener, true)
    keydownListener = null
  }
  prevFocusEl?.focus()
  prevFocusEl = null
}

watch(
  () => props.open,
  (open, wasOpen) => {
    if (open && !wasOpen) onOpen()
    else if (!open && wasOpen) onClose()
  },
  { immediate: true },
)

onUnmounted(() => {
  if (props.open) onClose()
})

// ── 动作 ────────────────────────────────────────────────────────────────────
function requestCancel() {
  if (busy.value) return
  emit('cancel')
  emit('update:open', false)
}

async function onConfirmClick() {
  if (busy.value) return
  if (!props.confirm) {
    emit('confirm')
    return
  }
  busy.value = true // 同步置位——连点在 await 前即被挡住
  errorMessage.value = ''
  try {
    await props.confirm()
    emit('update:open', false)
  } catch (e) {
    // 失败路径:保持开启 + inline 错误 + 按钮恢复,绝不静默关闭。
    errorMessage.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="open" class="cdlg">
    <div class="cdlg__backdrop" aria-hidden="true" />
    <div
      ref="dialogEl"
      class="cdlg__modal"
      :class="{ 'cdlg__modal--danger': danger }"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      tabindex="-1"
    >
      <h5 :id="titleId" class="cdlg__title">
        <slot name="title">{{ title }}</slot>
      </h5>
      <!-- aria-live:多步骤用例切换内文时向屏幕阅读器播报 -->
      <div class="cdlg__body" aria-live="polite">
        <slot />
      </div>
      <p v-if="errorMessage" class="cdlg__error" role="alert">{{ errorMessage }}</p>
      <div class="cdlg__actions">
        <button
          type="button"
          :class="confirmClass"
          :disabled="busy"
          :aria-busy="busy || undefined"
          @click="onConfirmClick"
        >{{ busy ? '处理中…' : confirmLabel }}</button>
        <button
          type="button"
          class="cdlg__btn cdlg__cancel"
          :disabled="busy"
          @click="requestCancel"
        >{{ cancelLabel }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cdlg {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  /* 高于 shell(SideNav 1050 / drawer overlay 1040),低于 Toast(1200)——
     确认等待期的错误 toast 仍要盖过 dialog。 */
  z-index: 1100;
}
.cdlg__backdrop {
  position: absolute;
  inset: 0;
  background: var(--backdrop);
}
.cdlg__modal {
  position: relative;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-glass);
  padding: var(--space-6);
  max-width: 500px;
  width: 90%;
}
.cdlg__modal--danger {
  border-color: var(--danger-soft);
}
.cdlg__title {
  margin: 0 0 var(--space-3);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
}
.cdlg__body {
  color: var(--text-primary);
  font-size: var(--text-base);
}
.cdlg__error {
  margin: var(--space-3) 0 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--danger-soft);
  color: var(--danger-text);
  font-size: var(--text-sm);
}
.cdlg__actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
.cdlg__btn {
  padding: var(--control-pad-y) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-base);
  cursor: pointer;
}
.cdlg__btn:disabled {
  cursor: not-allowed;
  opacity: 0.65;
}
.cdlg__confirm--primary {
  background: var(--primary);
  border: 1px solid var(--primary);
  color: var(--on-primary);
}
.cdlg__confirm--danger {
  background: var(--danger);
  border: 1px solid var(--danger);
  /* --dark 为常量近黑:在两种主题下对 --danger(#f87171)均 ≥4.5:1 */
  color: var(--dark);
}
.cdlg__cancel {
  background: transparent;
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
}
</style>
