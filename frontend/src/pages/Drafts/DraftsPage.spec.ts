import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/drafts', () => ({
  listDrafts: vi.fn(),
  scheduleDraft: vi.fn(),
  publishDraftNow: vi.fn(),
  cancelDraft: vi.fn(),
  deleteDraft: vi.fn(),
  bulkDeleteDrafts: vi.fn(),
  bulkPublishDraftsNow: vi.fn(),
  bulkCancelDrafts: vi.fn(),
}))

import * as api from '../../api/drafts'
import DraftsPage from './DraftsPage.vue'
import { useNotificationsStore } from '../../stores/notifications'

const PENDING = { id: 'p1', target_url: 'https://a.com/', status: 'pending', platform: 'velog' }
const SCHEDULED = {
  id: 's1', target_url: 'https://b.com/', status: 'scheduled', platform: 'medium',
  scheduled_at: '2026-06-20T09:00',
}

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(DraftsPage, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

function btn(w: VueWrapper, text: string) {
  return w.findAll('button').find((b) => b.text() === text)!
}

describe('DraftsPage', () => {
  it('renders pending controls (schedule input) and scheduled controls (cancel)', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING, SCHEDULED] })
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('.draft')).toHaveLength(2)
    // Pending row exposes a datetime input + 立即发布; scheduled row exposes 取消排程.
    expect(w.find('input[type="datetime-local"]').exists()).toBe(true)
    expect(btn(w, '立即发布')).toBeTruthy()
    expect(btn(w, '取消排程')).toBeTruthy()
  })

  it('shows the empty state when the queue is empty', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('草稿队列是空的')
  })

  it('shows the error state (role=alert) when the list fetch fails', async () => {
    vi.mocked(api.listDrafts).mockRejectedValue({ status: 500 })
    const w = mountPage()
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('schedules a pending draft with the chosen datetime', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
    vi.mocked(api.scheduleDraft).mockResolvedValue({
      items: [{ ...PENDING, status: 'scheduled' }],
      message: '已排程：2026-06-20 09:00',
    })
    const w = mountPage()
    await flushPromises()

    await w.find('input[type="datetime-local"]').setValue('2026-06-20T09:00')
    await btn(w, '排程').trigger('click')
    await flushPromises()

    expect(api.scheduleDraft).toHaveBeenCalledWith('p1', '2026-06-20T09:00')
  })

  it('refuses to schedule without a datetime (warns, no API call)', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()

    await btn(w, '排程').trigger('click')
    await flushPromises()

    expect(api.scheduleDraft).not.toHaveBeenCalled()
    expect(notify.toasts.some((t) => t.severity === 'warning')).toBe(true)
  })

  it('publishes a pending draft now', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
    vi.mocked(api.publishDraftNow).mockResolvedValue({ items: [PENDING] })
    const w = mountPage()
    await flushPromises()
    await btn(w, '立即发布').trigger('click')
    await flushPromises()
    expect(api.publishDraftNow).toHaveBeenCalledWith('p1')
  })

  it('cancels a scheduled draft', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [SCHEDULED] })
    vi.mocked(api.cancelDraft).mockResolvedValue({ items: [{ ...SCHEDULED, status: 'pending' }] })
    const w = mountPage()
    await flushPromises()
    await btn(w, '取消排程').trigger('click')
    await flushPromises()
    expect(api.cancelDraft).toHaveBeenCalledWith('s1')
  })

  it('surfaces a server warning message (lingering job) as a toast', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [SCHEDULED] })
    vi.mocked(api.deleteDraft).mockResolvedValue({
      items: [],
      message: '刪除失敗：無法同步刪除後台調度任務，該任務可能仍在運行！',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()
    await btn(w, '删除').trigger('click')
    await flushPromises()
    expect(api.deleteDraft).toHaveBeenCalledWith('s1')
    expect(notify.toasts.some((t) => t.message.includes('後台調度任務'))).toBe(true)
  })

  it('bulk-deletes selected drafts', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING, SCHEDULED] })
    vi.mocked(api.bulkDeleteDrafts).mockResolvedValue({ items: [], message: '已删除 1 项' })
    const w = mountPage()
    await flushPromises()
    await w.find('.draft input[type="checkbox"]').setValue(true)
    await w.find('.bulk-delete').trigger('click')
    await flushPromises()
    expect(api.bulkDeleteDrafts).toHaveBeenCalledWith(['p1'])
  })

  it('bulk-publishes selected drafts now (U3)', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING, SCHEDULED] })
    vi.mocked(api.bulkPublishDraftsNow).mockResolvedValue({
      items: [{ ...PENDING, status: 'scheduled' }, SCHEDULED],
      message: '正在批量发布 1 项，请稍候刷新页面',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()
    await w.find('.draft input[type="checkbox"]').setValue(true)
    await w.find('.bulk-publish-now').trigger('click')
    await flushPromises()
    expect(api.bulkPublishDraftsNow).toHaveBeenCalledWith(['p1'])
    expect(notify.toasts.some((t) => t.message.includes('批量发布'))).toBe(true)
  })

  it('bulk-cancels selected drafts', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [SCHEDULED] })
    vi.mocked(api.bulkCancelDrafts).mockResolvedValue({
      items: [{ ...SCHEDULED, status: 'pending' }],
      message: '已取消 1 项排程',
    })
    const w = mountPage()
    await flushPromises()
    await w.find('.draft input[type="checkbox"]').setValue(true)
    await w.find('.bulk-cancel').trigger('click')
    await flushPromises()
    expect(api.bulkCancelDrafts).toHaveBeenCalledWith(['s1'])
  })

  it('a double-submit rejected by the backend (409) surfaces a generic error toast, not a crash', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
    vi.mocked(api.bulkPublishDraftsNow).mockRejectedValue({
      name: 'ApiError', status: 409, message: 'Bulk publish already in progress',
    })
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()
    await w.find('.draft input[type="checkbox"]').setValue(true)
    await w.find('.bulk-publish-now').trigger('click')
    await flushPromises()
    expect(notify.toasts.some((t) => t.severity === 'error')).toBe(true)
  })

  it('bulk action buttons stay disabled with no selection', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
    const w = mountPage()
    await flushPromises()
    expect((w.find('.bulk-publish-now').element as HTMLButtonElement).disabled).toBe(true)
    expect((w.find('.bulk-cancel').element as HTMLButtonElement).disabled).toBe(true)
  })
})
