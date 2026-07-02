import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'

vi.mock('../api/client', () => ({
  sendJson: vi.fn(),
}))

import { sendJson } from '../api/client'
import ReportProblemPanel from './ReportProblemPanel.vue'
import { useNotificationsStore } from '../stores/notifications'
import { useReportPanelStore } from '../stores/reportPanel'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
})

function mountPanel() {
  return mount(ReportProblemPanel, { global: { plugins: [pinia] } })
}

describe('ReportProblemPanel — nav-bar entry (no reportId, POST path)', () => {
  it('renders nothing while the shared panel store is closed', () => {
    const w = mountPanel()
    expect(w.find('.report-panel').exists()).toBe(false)
  })

  it('edge case: blank input is rejected client-side with an inline message, no submission happens', async () => {
    const panel = useReportPanelStore()
    panel.open()
    const w = mountPanel()
    await w.vm.$nextTick()

    await w.find('textarea').setValue('   ')
    await w.find('.report-panel__submit').trigger('click')
    await w.vm.$nextTick()

    expect(sendJson).not.toHaveBeenCalled()
    expect(w.find('.report-panel__error').exists()).toBe(true)
    expect(w.find('.report-panel').exists()).toBe(true) // panel stays open
  })

  it('happy path: non-blank submit POSTs {message, source, severity} with NO reportId key, then closes + confirmation toast', async () => {
    vi.mocked(sendJson).mockResolvedValue({ id: 123 })
    const panel = useReportPanelStore()
    panel.open()
    const w = mountPanel()
    await w.vm.$nextTick()

    await w.find('textarea').setValue('按钮点击没有反应')
    await w.find('.report-panel__submit').trigger('click')
    await w.vm.$nextTick()
    await w.vm.$nextTick()

    expect(sendJson).toHaveBeenCalledTimes(1)
    const [method, path, body] = vi.mocked(sendJson).mock.calls[0]
    expect(method).toBe('POST')
    expect(path).toBe('/error-reports')
    expect(body).toMatchObject({ message: '按钮点击没有反应', source: 'manual', severity: 'error' })
    expect(body && typeof body === 'object' && 'reportId' in body).toBe(false)

    expect(panel.isOpen).toBe(false)
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('paired: a failed manual submit shows an inline error, panel stays open, no success toast (no background retry)', async () => {
    vi.mocked(sendJson).mockRejectedValue(new Error('boom'))
    const panel = useReportPanelStore()
    panel.open()
    const w = mountPanel()
    await w.vm.$nextTick()

    await w.find('textarea').setValue('同样的输入')
    await w.find('.report-panel__submit').trigger('click')
    await w.vm.$nextTick()
    await w.vm.$nextTick()

    expect(panel.isOpen).toBe(true)
    expect(w.find('.report-panel__error').exists()).toBe(true)
    const notify = useNotificationsStore()
    expect(notify.toasts.some((t) => t.severity === 'success')).toBe(false)
  })
})

describe('ReportProblemPanel — toast "补充说明" entry (reportId present, PATCH path)', () => {
  it('happy path: opening with a reportId PATCHes that id with {description}, then closes + confirmation toast', async () => {
    vi.mocked(sendJson).mockResolvedValue({ id: 42 })
    const panel = useReportPanelStore()
    panel.open(42)
    const w = mountPanel()
    await w.vm.$nextTick()

    expect(w.find('.report-panel__title').text()).toBe('补充说明')

    await w.find('textarea').setValue('补充：只有在 Safari 上会发生')
    await w.find('.report-panel__submit').trigger('click')
    await w.vm.$nextTick()
    await w.vm.$nextTick()

    expect(sendJson).toHaveBeenCalledTimes(1)
    const [method, path, body] = vi.mocked(sendJson).mock.calls[0]
    expect(method).toBe('PATCH')
    expect(path).toBe('/error-reports/42')
    expect(body).toMatchObject({ description: '补充：只有在 Safari 上会发生' })

    expect(panel.isOpen).toBe(false)
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })
})

describe('ReportProblemPanel — dashboard link', () => {
  it('links to the SPA error-reports dashboard route', async () => {
    const panel = useReportPanelStore()
    panel.open()
    const w = mountPanel()
    await w.vm.$nextTick()

    const link = w.find('.report-panel__dashboard-link')
    expect(link.attributes('href')).toBe('/app/error-reports')
  })
})
