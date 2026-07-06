import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/history', () => ({
  listHistory: vi.fn(),
  deleteHistory: vi.fn(),
  bulkDeleteHistory: vi.fn(),
  purgeFailedHistory: vi.fn(),
  recheckHistory: vi.fn(),
}))

import * as api from '../../api/history'
import HistoryPage from './HistoryPage.vue'
import { useNotificationsStore } from '../../stores/notifications'

const PUBLISHED = { id: '7', target_url: 'https://a.com/', status: 'published', platform: 'blogger' }
const FAILED = { id: '8', target_url: 'https://b.com/', status: 'failed', platform: 'medium' }

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountPage() {
  // Share the SAME pinia between the component and the test's store lookups.
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(HistoryPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('HistoryPage', () => {
  it('renders rows after the list fetch resolves', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('tbody tr')).toHaveLength(2)
    expect(w.text()).toContain('https://a.com/')
  })

  it('shows the empty state when there is no history', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('还没有发布记录')
    expect(w.findAll('tbody tr')).toHaveLength(0)
  })

  it('shows the StateBlock error state (role=alert) when the list fetch fails', async () => {
    vi.mocked(api.listHistory).mockRejectedValue({ status: 500 })
    const w = mountPage()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('deletes a row, refetches this page, and reflects the now-empty result', async () => {
    // Mutation endpoints return the full table (unchanged contract), not a
    // page-shaped envelope -- the page refetches from listHistory afterward
    // rather than reshaping deleteHistory's own response.
    vi.mocked(api.listHistory)
      .mockResolvedValueOnce({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
      .mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })
    vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()

    await w.find('.row-actions button:last-child').trigger('click') // 删除
    await flushPromises()

    expect(api.deleteHistory).toHaveBeenCalledWith('7')
    expect(w.findAll('tbody tr')).toHaveLength(0)
  })

  it('recheck surfaces the server message as a toast', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.recheckHistory).mockResolvedValue({
      items: [PUBLISHED],
      message: '已重新核实：状态 → published',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    await w.find('.row-actions button:first-child').trigger('click') // 重核
    await flushPromises()

    expect(api.recheckHistory).toHaveBeenCalledWith('7')
    expect(notify.toasts.some((t) => t.message.includes('已重新核实'))).toBe(true)
  })

  it('bulk-deletes the selected rows', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
    vi.mocked(api.bulkDeleteHistory).mockResolvedValue({ items: [], message: '已删除 1 条历史记录' })
    const w = mountPage()
    await flushPromises()

    await w.find('tbody tr input[type="checkbox"]').setValue(true) // select first row
    await w.find('.bulk-delete').trigger('click')
    await flushPromises()

    expect(api.bulkDeleteHistory).toHaveBeenCalledWith(['7'])
  })

  it('an action failure surfaces a classifyError toast (no raw server text)', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    vi.mocked(api.deleteHistory).mockRejectedValue({ status: 500, detail: 'stacktrace' })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    await w.find('.row-actions button:last-child').trigger('click')
    await flushPromises()

    expect(notify.toasts[0].severity).toBe('error')
    expect(notify.toasts[0].message).toContain('服务器出错了')
    expect(notify.toasts[0].message).not.toContain('stacktrace')
  })

  it('fetches with limit/offset=0 on mount (Plan 2026-07-02-001 U5)', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED], total: 1, limit: 50, offset: 0 })
    mountPage()
    await flushPromises()
    expect(api.listHistory).toHaveBeenCalledWith({ limit: 50, offset: 0 })
  })

  it('clicking next page fetches the next offset and clears the selection', async () => {
    vi.mocked(api.listHistory)
      .mockResolvedValueOnce({ items: [PUBLISHED], total: 120, limit: 50, offset: 0 })
      .mockResolvedValueOnce({ items: [FAILED], total: 120, limit: 50, offset: 50 })
    const w = mountPage()
    await flushPromises()

    await w.find('tbody tr input[type="checkbox"]').setValue(true) // select the only row
    expect(w.findAll('.data-table__pager button')).toHaveLength(2)

    const [, next] = w.findAll('.data-table__pager button')
    await next.trigger('click')
    await flushPromises()

    expect(api.listHistory).toHaveBeenCalledWith({ limit: 50, offset: 50 })
    // Selection made on page 1 must not survive the page change.
    expect(w.find('.bulk-delete').text()).toContain('(0)')
  })

  it('deleting the last row on the last page clamps back to the previous page', async () => {
    // Land on page 3 (offset 100) with a single remaining row; after deleting
    // it, the server-reported total (100) means offset 100 is now out of
    // range, so the page must clamp back to offset 50 and refetch there.
    vi.mocked(api.listHistory)
      .mockResolvedValueOnce({ items: [PUBLISHED], total: 101, limit: 50, offset: 0 })
      .mockResolvedValueOnce({ items: [FAILED], total: 101, limit: 50, offset: 100 })
    const w = mountPage()
    await flushPromises()

    const [, next] = w.findAll('.data-table__pager button')
    await next.trigger('click') // -> offset 50
    await flushPromises()
    const [, next2] = w.findAll('.data-table__pager button')
    await next2.trigger('click') // -> offset 100
    await flushPromises()

    vi.mocked(api.deleteHistory).mockResolvedValue({ items: [] })
    vi.mocked(api.listHistory).mockResolvedValueOnce({
      items: [], total: 100, limit: 50, offset: 100,
    }).mockResolvedValueOnce({
      items: [PUBLISHED], total: 100, limit: 50, offset: 50,
    })

    await w.find('.row-actions button:last-child').trigger('click') // 删除
    await flushPromises()

    // Last call must be the clamped refetch at offset 50, not the empty 100.
    const calls = vi.mocked(api.listHistory).mock.calls
    expect(calls[calls.length - 1]).toEqual([{ limit: 50, offset: 50 }])
  })
})
