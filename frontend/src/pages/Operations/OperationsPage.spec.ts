import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

vi.mock('../../api/operations', () => ({
  listOperations: vi.fn(),
}))

import * as api from '../../api/operations'
import type { OperationList, OperationStatus } from '../../api/operations'
import OperationsPage from './OperationsPage.vue'

const RUNNING_OP: OperationStatus = {
  op_id: 'op1',
  kind: 'publish',
  status: 'running',
  stage: 'publishing',
  stages: [],
  progress_pct: 40,
  detail: '',
  result: null,
  error: null,
  created_at: '2026-07-13T00:00:00Z',
  updated_at: '2026-07-13T00:00:00Z',
  running: true,
  done: false,
}

const LIST_WITH_ONE_OP: OperationList = { operations: [RUNNING_OP], count: 1 }

let pinia: ReturnType<typeof createPinia>
let queryClient: QueryClient

beforeEach(() => {
  vi.clearAllMocks()
  pinia = createPinia()
  setActivePinia(pinia)
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
})

function mountPage() {
  return mount(OperationsPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('OperationsPage', () => {
  it('renders rows after a successful load', async () => {
    vi.mocked(api.listOperations).mockResolvedValue(LIST_WITH_ONE_OP)
    const w = mountPage()
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.findAll('table.data-table tbody tr').length).toBe(1)
    expect(w.text()).toContain('发布')
  })

  it('with no data and an error, shows the table error UI', async () => {
    vi.mocked(api.listOperations).mockRejectedValue(new Error('network down'))
    const w = mountPage()
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(true)
    expect(w.findAll('table.data-table tbody tr').length).toBe(0)
  })

  // REGRESSION (final-review Fix 2): usePolledQuery keeps polling every 5s and
  // never reaches a terminal state on this dashboard. Wiring the raw
  // query.isError/query.error straight into DataTable's :error prop means a
  // single failed poll tick after a successful load flips DataTable's
  // blockState to 'error' (DataTable checks `error` BEFORE `items.length`,
  // see DataTable.vue's blockState computed) and replaces the already-loaded
  // task list with the error/retry UI, discarding keepPreviousData's cached
  // rows for no reason. The fix gates :error on `!query.data.value` so a
  // failed tick with cached data present never surfaces the error UI.
  it('a failed poll tick after a successful load keeps the task rows visible with no error UI', async () => {
    vi.useFakeTimers()
    vi.mocked(api.listOperations)
      .mockResolvedValueOnce(LIST_WITH_ONE_OP)
      .mockRejectedValueOnce(new Error('network blip'))
    const w = mountPage()

    await vi.advanceTimersByTimeAsync(0)
    expect(w.findAll('table.data-table tbody tr').length).toBe(1)

    await vi.advanceTimersByTimeAsync(5000) // next poll tick: fails
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.findAll('table.data-table tbody tr').length).toBe(1)
    expect(w.text()).toContain('发布')

    vi.useRealTimers()
  })
})
