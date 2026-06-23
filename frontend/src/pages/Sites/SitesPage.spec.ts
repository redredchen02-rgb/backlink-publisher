import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/sites', () => ({
  listSites: vi.fn(),
  getSitesWidgets: vi.fn(),
  getSiteForm: vi.fn(),
  saveSite: vi.fn(),
  setAutopilot: vi.fn(),
  scrapePreview: vi.fn(),
}))

import * as api from '../../api/sites'
import { ApiError } from '../../api/client'
import SitesPage from './SitesPage.vue'
import { useNotificationsStore } from '../../stores/notifications'

const SITE = {
  label: 'example.com',
  main_url: 'https://example.com/',
  autopilot_enabled: false,
  autopilot_interval: 86400,
  alert_pending: false,
  next_run_time_iso: null,
}
const WIDGETS = {
  plan_gap: { status: 'ok' as const, candidate_count: 3, target_count: 2, triggered_at: '2026-06-18 02:00 UTC' },
  citation_alert: null,
}

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.listSites).mockResolvedValue({ items: [SITE] })
  vi.mocked(api.getSitesWidgets).mockResolvedValue(WIDGETS)
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SitesPage, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

function btn(w: VueWrapper, text: string) {
  return w.findAll('button').find((b) => b.text() === text)!
}

describe('SitesPage', () => {
  it('renders the config form and the autopilot row', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.find('input[placeholder="https://your-site.com/"]').exists()).toBe(true)
    expect(w.find('.ap-table').exists()).toBe(true)
    expect(w.text()).toContain('example.com')
  })

  it('shows the empty state when no sites are configured', async () => {
    vi.mocked(api.listSites).mockResolvedValue({ items: [] })
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('尚无已配置站点')
  })

  it('saves a valid config and surfaces the autofilled notice', async () => {
    vi.mocked(api.saveSite).mockResolvedValue({
      ok: true,
      saved_domain: 'https://example.com',
      autofilled: ['branded_pool', 'partial_pool'],
      items: [SITE],
    })
    const w = mountPage()
    await flushPromises()

    await w.find('input[placeholder="https://your-site.com/"]').setValue('https://example.com/')
    await w.find('form.site-form').trigger('submit')
    await flushPromises()

    expect(api.saveSite).toHaveBeenCalledWith(expect.objectContaining({ main_url: 'https://example.com/' }))
    expect(w.text()).toContain('已自动派生')
    expect(w.text()).toContain('branded_pool')
  })

  it('renders inline field errors from a 422 problem+json', async () => {
    vi.mocked(api.saveSite).mockRejectedValue(
      new ApiError('invalid', 422, {
        errors: [
          { field: 'main_url', message: '必须 https' },
          { field: 'work_urls', message: '以下 URL 必须 https：x' },
        ],
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('form.site-form').trigger('submit')
    await flushPromises()

    const errs = w.findAll('.field-error').map((e) => e.text())
    expect(errs).toContain('必须 https')
    expect(errs.some((t) => t.includes('以下 URL 必须 https'))).toBe(true)
  })

  it('toggles autopilot with the selected interval', async () => {
    vi.mocked(api.setAutopilot).mockResolvedValue({
      ok: true,
      site_url: 'https://example.com/',
      enabled: true,
      next_run_time: '2026-06-19T09:00:00+00:00',
      last_run: null,
      items: [{ ...SITE, autopilot_enabled: true }],
    })
    const w = mountPage()
    await flushPromises()

    // Switch the interval to weekly, then enable.
    await w.find('select').setValue('604800')
    await w.find('input[role="switch"]').setValue(true)
    await flushPromises()

    expect(api.setAutopilot).toHaveBeenCalledWith('https://example.com/', true, 604800)
  })

  it('loads an existing site config into the form via 编辑', async () => {
    vi.mocked(api.getSiteForm).mockResolvedValue({
      form: {
        main_url: 'https://example.com/',
        list_url: 'https://example.com/list',
        work_urls: '',
        branded_pool: 'Example',
        partial_pool: '',
        exact_pool: '',
        work_anchor_templates: '',
        count: '10',
        insecure_tls: false,
      },
    })
    const w = mountPage()
    await flushPromises()

    await btn(w, '编辑').trigger('click')
    await flushPromises()

    expect(api.getSiteForm).toHaveBeenCalledWith('https://example.com/')
    expect((w.find('input[placeholder="https://your-site.com/list"]').element as HTMLInputElement).value).toBe(
      'https://example.com/list',
    )
  })

  it('renders the plan-gap weekly summary widget', async () => {
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('Plan-Gap 周报')
    expect(w.text()).toContain('补链 seed 候选')
  })

  it('renders the citation-share alert when present', async () => {
    vi.mocked(api.getSitesWidgets).mockResolvedValue({
      ...WIDGETS,
      citation_alert: { ts: '2026-06-18T00:00:00Z' },
    })
    const w = mountPage()
    await flushPromises()
    expect(w.find('.citation-alert').exists()).toBe(true)
    expect(w.text()).toContain('Citation Share 偏低')
  })
})
