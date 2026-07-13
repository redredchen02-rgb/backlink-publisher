<script setup lang="ts">
// Onboarding wizard (Plan 2026-07-09-001) — non-blocking first-run guide.
// A stepper overlay shown when the operator has incomplete setup and hasn't
// dismissed the guide. Each step's completion reflects real backend state
// (computed in OnboardingAPI), and "去設置" routes to the relevant page/section.
//
// Accessibility: role="dialog" + aria-modal, focus moved to the dialog on open,
// Tab is trapped within, Esc / overlay-click / × close (treated as "暫時跳過").
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useOnboardingStore } from '../stores/onboarding'
import type { OnboardingStep } from '../api/onboarding'

const store = useOnboardingStore()
const router = useRouter()
const dialogEl = ref<HTMLElement | null>(null)
const neverShow = ref(false)

const completedCount = computed(() => store.steps.filter((s) => s.done).length)
const totalCount = computed(() => store.steps.length)

function goTo(step: OnboardingStep) {
  router.push(step.cta)
  store.closeWizard()
}

function skip() {
  store.closeWizard()
}

async function finish() {
  if (neverShow.value) {
    await store.dismiss()
  } else {
    store.closeWizard()
  }
}

// Focus trap + Esc handling on the dialog element.
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    skip()
    return
  }
  if (e.key !== 'Tab' || !dialogEl.value) return
  const focusables = dialogEl.value.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], input, [tabindex]:not([tabindex="-1"])',
  )
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

watch(
  () => store.open,
  async (isOpen) => {
    if (isOpen) {
      await nextTick()
      dialogEl.value?.focus()
    }
  },
)
</script>

<template>
  <div v-if="store.open" class="onb-overlay" @click.self="skip">
    <div
      ref="dialogEl"
      class="onb"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onb-title"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <header class="onb__head">
        <h2 id="onb-title">新手引導</h2>
        <button type="button" class="onb__close" aria-label="暫時跳過" @click="skip">×</button>
      </header>

      <p class="onb__progress">已完成 {{ completedCount }} / {{ totalCount }}</p>

      <ol class="onb__steps">
        <li
          v-for="(step, i) in store.steps"
          :key="step.id"
          class="onb__step"
          :class="{ 'onb__step--done': step.done, 'onb__step--optional': step.optional }"
        >
          <span class="onb__num">{{ step.done ? '✓' : i + 1 }}</span>
          <div class="onb__body">
            <div class="onb__title">
              {{ step.title }}
              <span v-if="step.optional" class="onb__tag">建議</span>
            </div>
            <p class="onb__rationale">{{ step.rationale }}</p>
            <button type="button" class="onb__cta" :disabled="step.done" @click="goTo(step)">
              {{ step.done ? '已完成' : '去設置 →' }}
            </button>
          </div>
        </li>
      </ol>

      <footer class="onb__foot">
        <label class="onb__never">
          <input v-model="neverShow" type="checkbox" />
          完成全部後不再提示
        </label>
        <div class="onb__actions">
          <button type="button" class="onb__skip" @click="skip">暫時跳過</button>
          <button type="button" class="onb__finish" @click="finish">
            {{ neverShow ? '完成並不再顯示' : '完成' }}
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.onb-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
  padding: 1rem;
}
.onb {
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  max-width: 560px;
  width: 100%;
  max-height: 90vh;
  overflow-y: auto;
  padding: 1.25rem;
  outline: none;
}
.onb__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.onb__head h2 {
  margin: 0;
  font-size: var(--text-2xl);
}
.onb__close {
  background: none;
  border: none;
  font-size: 1.5rem;
  line-height: 1;
  cursor: pointer;
  color: var(--text-secondary);
}
.onb__progress {
  color: var(--text-secondary);
  margin: 0.5rem 0 1rem;
}
.onb__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.onb__step {
  display: flex;
  gap: 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0.75rem;
}
.onb__step--done {
  border-color: var(--success);
}
.onb__num {
  flex: 0 0 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
}
.onb__step--done .onb__num {
  background: var(--success);
  color: #fff;
  border-color: transparent;
}
.onb__body {
  min-width: 0;
  flex: 1;
}
.onb__title {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.onb__tag {
  font-size: var(--text-xs);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0 0.4rem;
}
.onb__rationale {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  margin: 0.25rem 0 0.5rem;
}
.onb__cta {
  font-size: var(--text-sm);
}
.onb__cta:disabled {
  opacity: 0.6;
  cursor: default;
}
.onb__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-top: 1rem;
  flex-wrap: wrap;
}
.onb__actions {
  display: flex;
  gap: 0.5rem;
}
</style>
