import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/history', () => ({
  listHistory: vi.fn(),
  deleteHistory: vi.fn(),
  bulkDeleteHistory: vi.fn(),
  bulkRecheckHistory: vi.fn(),
  purgeFailedHistory: vi.fn(),
  recheckHistory: vi.fn(),
}))

import * as api from '../../api/history'
import HistoryPage from './HistoryPage.vue'
import Icon from '../../components/Icon.vue'
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

  it('deletes a row and writes the refreshed list back into the table', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
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

  it('renders the box-arrow-up-right Icon for row links with a valid, known icon name', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(api.listHistory).mockResolvedValue({
      items: [{ ...PUBLISHED, article_urls: ['https://c.com/article'] }],
    })
    const w = mountPage()
    await flushPromises()

    const icons = w.findAllComponents(Icon)
    expect(icons.length).toBeGreaterThan(0)
    for (const icon of icons) {
      const svg = icon.find('svg')
      expect(svg.exists()).toBe(true)
      expect(svg.findAll('path').length).toBeGreaterThan(0)
    }
    expect(warnSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('bulk-rechecks the selected rows (U3)', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
    vi.mocked(api.bulkRecheckHistory).mockResolvedValue({
      items: [PUBLISHED, FAILED],
      message: '已核实 1 条：1 升为已发布，0 标为失败，0 跳过',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    await w.find('tbody tr input[type="checkbox"]').setValue(true) // select first row
    await w.find('.bulk-recheck').trigger('click')
    await flushPromises()

    expect(api.bulkRecheckHistory).toHaveBeenCalledWith(['7'])
    expect(notify.toasts.some((t) => t.message.includes('已核实'))).toBe(true)
  })

  it('bulk-recheck button stays disabled with no selection', async () => {
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED] })
    const w = mountPage()
    await flushPromises()

    const btn = w.find('.bulk-recheck')
    expect((btn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('a successful bulk action only deselects the ids it actually submitted (code review)', async () => {
    // If the user reselects a DIFFERENT row while the first bulk call is still
    // in flight, that reselection must survive -- run() must not blanket-clear
    // `selected` on success, only remove the ids this call actually acted on.
    vi.mocked(api.listHistory).mockResolvedValue({ items: [PUBLISHED, FAILED] })
    let resolveDelete!: (v: { items: typeof PUBLISHED[]; message?: string }) => void
    const pending = new Promise<{ items: typeof PUBLISHED[]; message?: string }>((res) => {
      resolveDelete = res
    })
    vi.mocked(api.bulkDeleteHistory).mockReturnValue(pending)
    const w = mountPage()
    await flushPromises()

    const checkboxes = w.findAll('tbody tr input[type="checkbox"]')
    await checkboxes[0].setValue(true) // select PUBLISHED (id 7)
    await w.find('.bulk-delete').trigger('click') // in-flight, still holding [7]

    await checkboxes[1].setValue(true) // reselect FAILED (id 8) mid-flight

    resolveDelete({ items: [FAILED] }) // id 7 deleted server-side
    await flushPromises()

    expect(api.bulkDeleteHistory).toHaveBeenCalledWith(['7'])
    const remainingCheckbox = w.find('tbody tr input[type="checkbox"]')
    expect((remainingCheckbox.element as HTMLInputElement).checked).toBe(true)
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
})
