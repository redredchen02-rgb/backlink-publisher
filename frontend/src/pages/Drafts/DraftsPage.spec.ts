import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { MutationCache, QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

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
import { ApiError, _resetCsrfForTest } from '../../api/client'
import { reportMutationError, _resetCaptureStateForTest } from '../../lib/errorCapture'

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
  // Mirrors main.ts's QueryClient construction (MutationCache.onError ->
  // reportMutationError) so W13's useMutation migration is exercised
  // end-to-end, not just "does the toast still work".
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    mutationCache: new MutationCache({
      onError: (error, _variables, _onMutateResult, mutation) =>
        reportMutationError(error, mutation.options.mutationKey),
    }),
  })
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
    vi.mocked(api.bulkPublishDraftsNow).mockRejectedValue(
      new ApiError('Bulk publish already in progress', 409, { error_class: 'already_running' }),
    )
    const w = mountPage()
    const notify = useNotificationsStore()
    await flushPromises()
    await w.find('.draft input[type="checkbox"]').setValue(true)
    await w.find('.bulk-publish-now').trigger('click')
    await flushPromises()
    expect(notify.toasts.some((t) => t.severity === 'error')).toBe(true)
    // Code review: busy/disabled must reset after a failed call too, so the
    // operator can retry -- not just after a successful one.
    expect((w.find('.bulk-publish-now').element as HTMLButtonElement).disabled).toBe(false)
  })

  it('a successful bulk action only deselects the ids it actually submitted (code review)', async () => {
    // If the user reselects a DIFFERENT row while the first bulk call is still
    // in flight, that reselection must survive -- run() must not blanket-clear
    // `selected` on success, only remove the ids this call actually acted on.
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING, SCHEDULED] })
    const pending = (() => {
      let resolve!: (v: { items: typeof PENDING[]; message?: string }) => void
      const promise = new Promise<{ items: typeof PENDING[]; message?: string }>((res) => {
        resolve = res
      })
      return { promise, resolve }
    })()
    vi.mocked(api.bulkDeleteDrafts).mockReturnValue(pending.promise)
    const w = mountPage()
    await flushPromises()

    const checkboxes = w.findAll('.draft input[type="checkbox"]')
    await checkboxes[0].setValue(true) // select PENDING (p1)
    await w.find('.bulk-delete').trigger('click') // in-flight, still holding [p1]

    await checkboxes[1].setValue(true) // reselect SCHEDULED (s1) mid-flight

    pending.resolve({ items: [SCHEDULED] }) // p1 deleted server-side
    await flushPromises()

    expect(api.bulkDeleteDrafts).toHaveBeenCalledWith(['p1'])
    // s1's checkbox (reselected mid-flight) must still be checked afterward.
    const remainingCheckbox = w.find('.draft input[type="checkbox"]')
    expect((remainingCheckbox.element as HTMLInputElement).checked).toBe(true)
  })

  it('bulk action buttons stay disabled with no selection', async () => {
    vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
    const w = mountPage()
    await flushPromises()
    expect((w.find('.bulk-publish-now').element as HTMLButtonElement).disabled).toBe(true)
    expect((w.find('.bulk-cancel').element as HTMLButtonElement).disabled).toBe(true)
  })

  // ── W13: mutation error-report coverage (discovery #4 / D7 useMutation migration) ──
  //
  // End-to-end through the REAL lib/errorCapture module + a real
  // MutationCache (see mountPage above) — stubs `fetch` and asserts on
  // POST /error-reports calls, proving DraftsPage's useMutation migration
  // actually reaches MutationCache.onError -> reportMutationError -> D8.

  interface ReportCall {
    url: string
    body: Record<string, unknown>
  }

  function installErrorReportFetchStub(): ReportCall[] {
    const calls: ReportCall[] = []
    let nextId = 1
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push({ url: String(url), body: init?.body ? JSON.parse(String(init.body)) : {} })
        return new Response(
          JSON.stringify({ id: `draft-report-${nextId++}` }),
          { status: 201, headers: { 'Content-Type': 'application/json' } },
        )
      }),
    )
    return calls
  }

  describe('W13: error-reports coverage via useMutation', () => {
    beforeEach(() => {
      _resetCaptureStateForTest()
      document.head.innerHTML = '<meta name="csrf-token" content="test-token">'
    })

    afterEach(() => {
      vi.unstubAllGlobals()
      _resetCsrfForTest()
      document.head.innerHTML = ''
    })

    it('a 500 delete failure shows the classified toast AND submits an error-report', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
      vi.mocked(api.deleteDraft).mockRejectedValue(new ApiError('server exploded', 500, { detail: 'boom' }))
      const w = mountPage()
      const notify = useNotificationsStore()
      await flushPromises()

      await btn(w, '删除').trigger('click')
      await flushPromises()

      expect(notify.toasts.some((t) => t.severity === 'error' && t.message.includes('服务器出错了'))).toBe(
        true,
      )
      expect(calls).toHaveLength(1)
      expect(calls[0].url).toContain('/error-reports')
    })

    it('a 422 delete failure does NOT submit an error-report (D8)', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
      vi.mocked(api.deleteDraft).mockRejectedValue(new ApiError('rejected', 422, { detail: 'x' }))
      const w = mountPage()
      await flushPromises()

      await btn(w, '删除').trigger('click')
      await flushPromises()

      expect(calls).toHaveLength(0)
    })

    it('a 403 (non-422 4xx, e.g. CSRF) delete failure IS reported', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
      vi.mocked(api.deleteDraft).mockRejectedValue(new ApiError('forbidden', 403, {}))
      const w = mountPage()
      await flushPromises()

      await btn(w, '删除').trigger('click')
      await flushPromises()

      expect(calls).toHaveLength(1)
    })

    it('a network error (TypeError) on publish-now is reported', async () => {
      const calls = installErrorReportFetchStub()
      vi.mocked(api.listDrafts).mockResolvedValue({ items: [PENDING] })
      vi.mocked(api.publishDraftNow).mockRejectedValue(new TypeError('Failed to fetch'))
      const w = mountPage()
      await flushPromises()

      await btn(w, '立即发布').trigger('click')
      await flushPromises()

      expect(calls).toHaveLength(1)
    })
  })
})
