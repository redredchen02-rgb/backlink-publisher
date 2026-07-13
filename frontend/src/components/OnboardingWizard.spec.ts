// Plan 2026-07-09-001 — OnboardingWizard mount/behavior test.
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('../api/onboarding', () => ({
  getOnboardingStatus: vi.fn(),
  dismissOnboarding: vi.fn().mockResolvedValue({ ok: true }),
  resetOnboarding: vi.fn().mockResolvedValue({ ok: true }),
}))

import * as api from '../api/onboarding'
import OnboardingWizard from './OnboardingWizard.vue'
import { useOnboardingStore } from '../stores/onboarding'

const STATUS = {
  dismissed: false,
  all_done: false,
  steps: [
    { id: 'connect_channel', title: '連接你的第一個發布渠道', rationale: 'r', optional: false, cta: '/settings#sec-channels', done: false },
    { id: 'configure_llm', title: '配置 LLM（建議）', rationale: 'r', optional: true, cta: '/settings#sec-ai', done: false },
    { id: 'add_targets', title: '添加目標站點與錨文本池', rationale: 'r', optional: false, cta: '/settings#sec-keywords', done: false },
    { id: 'create_campaign', title: '建立你的第一個 Campaign', rationale: 'r', optional: false, cta: '/batch-campaign', done: false },
    { id: 'publish_first', title: '發布你的第一篇文章', rationale: 'r', optional: false, cta: '/publish', done: false },
  ],
}

let pinia: ReturnType<typeof createPinia>
let router: ReturnType<typeof createRouter>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: {} as never }] })
  vi.clearAllMocks()
  vi.mocked(api.getOnboardingStatus).mockResolvedValue(STATUS as never)
})

function mountWizard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(OnboardingWizard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }], router] },
  })
}

describe('OnboardingWizard', () => {
  it('renders all 5 steps once opened', async () => {
    const w = mountWizard()
    const store = useOnboardingStore()
    store.openWizard()
    await flushPromises()
    await w.vm.$nextTick()

    expect(w.findAll('.onb__step').length).toBe(5)
    expect(w.text()).toContain('連接你的第一個發布渠道')
    expect(w.text()).toContain('發布你的第一篇文章')
  })

  it('marks the optional step with the 建議 tag', async () => {
    const w = mountWizard()
    const store = useOnboardingStore()
    store.openWizard()
    await flushPromises()
    await w.vm.$nextTick()

    expect(w.findAll('.onb__step--optional').length).toBe(1)
  })

  it('navigates to the step CTA and closes when 去設置 clicked', async () => {
    const push = vi.spyOn(router, 'push').mockImplementation(() => Promise.resolve() as never)
    const w = mountWizard()
    const store = useOnboardingStore()
    store.openWizard()
    await flushPromises()
    await w.vm.$nextTick()

    const cta = w.find('.onb__cta')
    await cta.trigger('click')

    expect(push).toHaveBeenCalledWith('/settings#sec-channels')
    expect(store.open).toBe(false)
  })

  it('calls dismissOnboarding when 完成並不再顯示 clicked', async () => {
    const w = mountWizard()
    const store = useOnboardingStore()
    store.openWizard()
    await flushPromises()
    await w.vm.$nextTick()

    await w.find('input[type="checkbox"]').setValue(true)
    await w.vm.$nextTick()

    const finish = w.findAll('button').find((b) => b.text().includes('完成並不再顯示'))
    expect(finish).toBeTruthy()
    await finish!.trigger('click')

    expect(api.dismissOnboarding).toHaveBeenCalled()
  })

  it('closes (skip) on Esc without dismissing', async () => {
    const w = mountWizard()
    const store = useOnboardingStore()
    store.openWizard()
    await flushPromises()
    await w.vm.$nextTick()

    await w.find('.onb').trigger('keydown', { key: 'Escape' })

    expect(store.open).toBe(false)
    expect(api.dismissOnboarding).not.toHaveBeenCalled()
  })
})
