import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
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

// Publish runs as an async operation (Plan 2026-07-09 P2): the store enqueues
// via createOperation and <OperationProgress> polls getOperation until terminal.
vi.mock('../../api/operations', () => ({
  createOperation: vi.fn(),
  getOperation: vi.fn(),
  cancelOperation: vi.fn(),
  listOperations: vi.fn(),
}))

import * as api from '../../api/pipeline'
import { createOperation, getOperation } from '../../api/operations'
import OperationProgress from '../../components/OperationProgress.vue'
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

/** ProfileSelector (nested in the config fieldset) also renders buttons, so a
 *  plain `.find('button')` is ambiguous — match by visible text instead. */
function btn(w: VueWrapper, text: string) {
  return w.findAll('button').find((b) => b.text() === text)!
}

/** Terminal op payload as the worker stores it (note n_failed, not n_total). */
function successOp(result: Record<string, unknown>) {
  return {
    op_id: 'op-1',
    kind: 'publish',
    status: 'success',
    stage: '发布',
    stages: ['发布'],
    progress_pct: 100,
    running: false,
    result,
  }
}

describe('PublishWorkbench — async publish UX (operation-progress P2)', () => {
  it('disables the submit control and renders OperationProgress while publishing', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    store.validated = [{ id: 'a' }] // reveal the publish step
    store.publishing = true
    store.publishOpId = 'op-1'
    vi.mocked(getOperation).mockResolvedValue({
      op_id: 'op-1', kind: 'publish', status: 'running', stage: '发布',
      stages: ['发布'], progress_pct: 50, running: true,
    } as never)
    await nextTick()

    const btn = w.find('.publish-btn')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(w.findComponent(OperationProgress).exists()).toBe(true)
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

    const busy = w.find('.publish-busy')
    expect(busy.attributes('aria-live')).toBe('polite')
    expect(busy.text()).toContain('仍在进行，可能已完成，请勿重复提交')
  })

  it('a publish enqueue failure surfaces a classifyError toast (never raw server text)', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    const notify = useNotificationsStore()
    store.validated = [{ id: 'a' }]
    await nextTick() // render the publish step
    vi.mocked(createOperation).mockRejectedValue({ status: 500, detail: 'stacktrace leak' })

    await w.find('.publish-btn').trigger('click')
    await flushPromises()

    expect(notify.toasts).toHaveLength(1)
    expect(notify.toasts[0].severity).toBe('error')
    expect(notify.toasts[0].message).toContain('服务器出错了') // taxonomy copy
    expect(notify.toasts[0].message).not.toContain('stacktrace leak') // no raw text
  })

  it('shows the result card with per-row outcomes after the op settles successfully', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    store.validated = [{ id: 'a' }]
    await nextTick() // render the publish step
    vi.mocked(createOperation).mockResolvedValue({ op_id: 'op-1', kind: 'publish' })
    vi.mocked(getOperation).mockResolvedValue(successOp({
      state: 'partial_success',
      n_ok: 1,
      n_failed: 1,
      failure_detail: 'one failed',
      results: [{ published_url: 'https://blog/ok' }, { error: 'nope' }],
    }) as never)

    await w.find('.publish-btn').trigger('click')
    await flushPromises() // enqueue → OperationProgress mounts → first poll settles
    await flushPromises()

    const result = w.find('.result')
    expect(result.exists()).toBe(true)
    expect(result.attributes('data-state')).toBe('partial_success')
    expect(result.text()).toContain('1/2 成功')
    expect(result.text()).toContain('https://blog/ok')
  })

  it('a partial-failure publish never renders all_success styling — the failed row is marked, not hidden as success (R3 action 9)', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    store.validated = [{ id: 'a' }]
    await nextTick()
    vi.mocked(createOperation).mockResolvedValue({ op_id: 'op-1', kind: 'publish' })
    vi.mocked(getOperation).mockResolvedValue(successOp({
      state: 'partial_success',
      n_ok: 1,
      n_failed: 1,
      failure_detail: 'one failed',
      results: [{ published_url: 'https://blog/ok' }, { error: 'nope' }],
    }) as never)

    await w.find('.publish-btn').trigger('click')
    await flushPromises()
    await flushPromises()

    const result = w.find('.result')
    // Never the all_success selector/state for a response that reports a failure.
    expect(w.find(".result[data-state='all_success']").exists()).toBe(false)
    expect(result.attributes('data-state')).toBe('partial_success')
    // The failed row must carry the 'fail' marker (✗), not 'ok' (✓).
    const rows = result.findAll('.rows li')
    expect(rows[0].find('.ok').exists()).toBe(true)
    expect(rows[1].find('.fail').exists()).toBe(true)
    expect(rows[1].find('.ok').exists()).toBe(false)
    expect(rows[1].text()).toContain('nope')
  })

  it('a failed op keeps OperationProgress visible and mirrors the error into stage-error + toast', async () => {
    const w = mountWorkbench()
    const store = usePublishStore()
    const notify = useNotificationsStore()
    store.validated = [{ id: 'a' }]
    await nextTick()
    vi.mocked(createOperation).mockResolvedValue({ op_id: 'op-1', kind: 'publish' })
    vi.mocked(getOperation).mockResolvedValue({
      op_id: 'op-1', kind: 'publish', status: 'failed', stage: '发布',
      stages: ['发布'], progress_pct: 50, running: false, error: 'adapter blew up',
    } as never)

    await w.find('.publish-btn').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(store.publishing).toBe(false)
    expect(store.publishOpId).toBe('op-1') // terminal error stays on screen
    expect(w.findComponent(OperationProgress).exists()).toBe(true)
    expect(w.find('.result').exists()).toBe(false)
    expect(notify.toasts.length).toBeGreaterThan(0)
  })
})

describe('PublishWorkbench — empty-state notice (no silent no-op on zero-row plan)', () => {
  it('shows a persistent empty notice when planning succeeds with zero rows', async () => {
    const w = mountWorkbench()
    vi.mocked(api.planBacklinks).mockResolvedValue({ plans: [] })

    await w.find('textarea').setValue('https://a.com/')
    await btn(w, '生成文章计划').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('未生成任何文章计划')
    expect(w.find('fieldset.card').exists()).toBe(true) // step 1 still visible
  })

  it('clears the empty notice once a subsequent plan attempt returns rows', async () => {
    const w = mountWorkbench()
    vi.mocked(api.planBacklinks).mockResolvedValueOnce({ plans: [] })

    await w.find('textarea').setValue('https://a.com/')
    await btn(w, '生成文章计划').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('未生成任何文章计划')

    vi.mocked(api.planBacklinks).mockResolvedValueOnce({ plans: [{ id: 'a' }] })
    await btn(w, '生成文章计划').trigger('click')
    await flushPromises()

    expect(w.text()).not.toContain('未生成任何文章计划')
  })
})

describe('PublishWorkbench — persistent in-page error indicators (R3 action 6/7)', () => {
  it('a plan failure shows a persistent classifyError message next to step 1 (not just a toast)', async () => {
    const w = mountWorkbench()
    vi.mocked(api.planBacklinks).mockRejectedValue({ status: 500, detail: 'stacktrace leak' })

    await w.find('textarea').setValue('https://a.com/')
    await btn(w, '生成文章计划').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('服务器出错了')
    expect(w.text()).not.toContain('stacktrace leak')
  })

  it('shows a persistent, retryable indicator when the platform bootstrap load fails', async () => {
    vi.mocked(api.boundPlatforms).mockRejectedValue({ status: 500, detail: 'boom' })
    const w = mountWorkbench()
    await flushPromises()

    expect(w.find('.section-error').exists()).toBe(true)
    expect(w.text()).toContain('服务器出错了')
    // The form must still be usable — falls back to the default platform.
    expect(w.find('select').exists()).toBe(true)

    vi.mocked(api.boundPlatforms).mockResolvedValue({
      platforms: [{ slug: 'blogger', display_name: 'Blogger' }],
    })
    await w.find('.section-error button').trigger('click')
    await flushPromises()

    expect(w.find('.section-error').exists()).toBe(false)
  })
})
