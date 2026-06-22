import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/pipeline', () => ({
  planBacklinks: vi.fn(),
  validateBacklinks: vi.fn(),
  publishBacklinks: vi.fn(),
  boundPlatforms: vi.fn().mockResolvedValue({ platforms: [] }),
}))

// The config block now embeds ProfileSelector (a TanStack-Query consumer).
vi.mock('../../api/profiles', () => ({
  getProfiles: vi.fn().mockResolvedValue({ items: [] }),
  saveProfile: vi.fn(),
  deleteProfile: vi.fn(),
}))

import * as api from '../../api/pipeline'
import PublishWorkbench from './PublishWorkbench.vue'
import { usePublishStore } from '../../stores/publish'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.boundPlatforms).mockResolvedValue({ platforms: [] })
})

afterEach(() => {
  vi.useRealTimers()
})

function mountWorkbench() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(PublishWorkbench, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('PublishWorkbench — busy-state publish UX (degraded, no task-id)', () => {
  it('disables the submit control and shows the busy copy while publishing', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    store.validated = [{ id: 'a' }] // reveal the publish step
    store.publishing = true
    await nextTick()

    const btn = w.find('.publish-btn')
    expect(btn.attributes('disabled')).toBeDefined()
    const busy = w.find('.publish-busy')
    expect(busy.exists()).toBe(true)
    expect(busy.attributes('aria-live')).toBe('polite')
    expect(busy.text()).toContain('发布进行中，请勿关闭此页')
  })

  it('switches to the soft-timeout copy after the timeout (never looks frozen)', async () => {
    vi.useFakeTimers()
    const w = mountWorkbench()
    const store = usePublishStore()
    store.validated = [{ id: 'a' }]
    store.publishing = true
    await nextTick() // let the watcher arm the soft-timeout timer

    vi.advanceTimersByTime(45_000)
    await nextTick()

    expect(w.find('.publish-busy').text()).toContain('仍在进行，可能已完成，请勿重复提交')
  })

  it('a publish failure surfaces a classifyError toast (never raw server text)', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    const notify = useNotificationsStore()
    store.validated = [{ id: 'a' }]
    await nextTick() // render the publish step
    vi.mocked(api.publishBacklinks).mockRejectedValue({ status: 500, detail: 'stacktrace leak' })

    await w.find('.publish-btn').trigger('click')
    await flushPromises()

    expect(notify.toasts).toHaveLength(1)
    expect(notify.toasts[0].severity).toBe('error')
    expect(notify.toasts[0].message).toContain('服务器出错了') // taxonomy copy
    expect(notify.toasts[0].message).not.toContain('stacktrace leak') // no raw text
  })

  it('shows the result card with per-row outcomes after a successful publish', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    store.validated = [{ id: 'a' }]
    await nextTick() // render the publish step
    vi.mocked(api.publishBacklinks).mockResolvedValue({
      state: 'partial_success',
      n_ok: 1,
      n_total: 2,
      failure_detail: 'one failed',
      results: [{ published_url: 'https://blog/ok' }, { error: 'nope' }],
    })

    await w.find('.publish-btn').trigger('click')
    await flushPromises()

    const result = w.find('.result')
    expect(result.exists()).toBe(true)
    expect(result.attributes('data-state')).toBe('partial_success')
    expect(result.text()).toContain('1/2 成功')
    expect(result.text()).toContain('https://blog/ok')
  })
})
