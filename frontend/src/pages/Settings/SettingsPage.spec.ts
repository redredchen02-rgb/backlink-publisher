import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getKeywordPools: vi.fn(),
  saveKeywordPools: vi.fn(),
  getScheduleSettings: vi.fn(),
  saveScheduleSettings: vi.fn(),
  // ChannelsCard (rendered by SettingsPage) hydrates from getChannels.
  getChannels: vi.fn(),
  // ChannelBindingCard (rendered by SettingsPage) hydrates from getChannelForms.
  getChannelForms: vi.fn(),
  saveChannelCredential: vi.fn(),
  saveChannelToken: vi.fn(),
  // MediumCard (rendered by SettingsPage) hydrates from getMediumStatus.
  getMediumStatus: vi.fn(),
  launchMediumLogin: vi.fn(),
  probeMediumLogin: vi.fn(),
  clearMediumLogin: vi.fn(),
  clearMediumOauth: vi.fn(),
  // VelogCard (rendered by SettingsPage) hydrates from getVelogStatus.
  getVelogStatus: vi.fn(),
  velogLogin: vi.fn(),
  // BloggerCard (rendered by SettingsPage) hydrates from getBloggerStatus.
  getBloggerStatus: vi.fn(),
  saveBloggerOauth: vi.fn(),
  revokeBlogger: vi.fn(),
  // NotionCard (rendered by SettingsPage) hydrates from getNotionStatus.
  getNotionStatus: vi.fn(),
  saveNotionToken: vi.fn(),
  clearNotionToken: vi.fn(),
  // BlogIdsCard (rendered by SettingsPage) hydrates from getBlogIds.
  getBlogIds: vi.fn(),
  saveBlogIds: vi.fn(),
  // LlmSettingsCard (rendered by SettingsPage) hydrates from getLlmConfig.
  getLlmConfig: vi.fn(),
  saveLlmConfig: vi.fn(),
  clearLlmConfig: vi.fn(),
  testLlmConnection: vi.fn(),
  testLlmGeneration: vi.fn(),
  testImageGen: vi.fn(),
  generateImageSample: vi.fn(),
}))

const LLM_CONFIG = {
  endpoint: '',
  model: '',
  temperature: 0.7,
  system_prompt: '',
  article_system_prompt: '',
  use_article_gen: false,
  use_image_gen: false,
  image_gen_endpoint: '',
  image_gen_model: '',
  image_gen_banner_size: '1200x630',
  has_api_key: false,
  has_image_gen_api_key: false,
}

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import SettingsPage from './SettingsPage.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useSettingsDirtyStore } from '../../stores/settingsDirty'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getKeywordPools).mockResolvedValue({
    targets: ['https://x.com'],
    pools: { 'https://x.com': ['alpha', 'beta'] },
  })
  vi.mocked(api.getScheduleSettings).mockResolvedValue({
    min_interval_hours: 4,
    jitter_minutes: 30,
  })
  vi.mocked(api.getLlmConfig).mockResolvedValue({ ...LLM_CONFIG })
  vi.mocked(api.getChannels).mockResolvedValue({ channels: [] })
  vi.mocked(api.getChannelForms).mockResolvedValue({ forms: [] })
  vi.mocked(api.getMediumStatus).mockResolvedValue({
    browser: {
      state: 'no_profile',
      playwright_installed: true,
      profile_has_cookies: false,
      cookies_age_days: null,
      singleton_lock_present: false,
      logged_in: false,
    },
    oauth_token_exists: false,
  })
  vi.mocked(api.getVelogStatus).mockResolvedValue({
    state: 'err', label: '未绑定', guide: '运行: velog-login', cookies_path: '', count: 0, cap: 5,
  })
  vi.mocked(api.getBloggerStatus).mockResolvedValue({
    authorized: false, client_id: '', client_secret_set: false,
    callback_uri: 'http://localhost:8888/settings/blogger/oauth-callback',
  })
  vi.mocked(api.getBlogIds).mockResolvedValue({ blog_ids: {} })
  vi.mocked(api.getNotionStatus).mockResolvedValue({ configured: false, database_id: '' })
})

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SettingsPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

/** Like mountPage(), but also hands back the QueryClient so a test can push
 *  new cache data directly (`setQueryData`) — simulating a refetch triggered
 *  by something *other* than window focus (invalidation elsewhere, a manual
 *  refetch, revisiting the route), which is exactly the trigger W1's
 *  `refetchOnWindowFocus: false` does NOT cover. */
function mountPageWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(SettingsPage, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
  return { wrapper, queryClient }
}

describe('SettingsPage — global config', () => {
  it('hydrates the keyword editor and the schedule form from GET', async () => {
    const w = mountPage()
    await flushPromises()
    const ta = w.find('textarea')
    expect(ta.exists()).toBe(true)
    expect((ta.element as HTMLTextAreaElement).value).toBe('alpha\nbeta')
    const num = w.find('input[type="number"]')
    expect((num.element as HTMLInputElement).value).toBe('4')
  })

  it('saves keyword pools → success toast, sending trimmed non-empty lines', async () => {
    vi.mocked(api.saveKeywordPools).mockResolvedValue({ ok: true, message: '关键词已保存' })
    const w = mountPage()
    await flushPromises()
    await w.find('textarea').setValue('alpha\n  gamma  \n\n')
    await w.find('[data-test="keyword-form"]').trigger('submit')
    await flushPromises()
    expect(api.saveKeywordPools).toHaveBeenCalledWith({ 'https://x.com': ['alpha', 'gamma'] })
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('W6: a 422 keyword rejection renders inline under the keyword form, not a global toast', async () => {
    vi.mocked(api.saveKeywordPools).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '关键词过长（>60字符）: XXX…' }),
    )
    const w = mountPage()
    await flushPromises()
    await w.find('[data-test="keyword-form"]').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="keywords-form-error"]').text()).toContain('关键词过长')
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('W6: a 422 schedule rejection renders inline under the schedule form, not a global toast', async () => {
    vi.mocked(api.saveScheduleSettings).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '保存失败: ValueError' }),
    )
    const w = mountPage()
    await flushPromises()
    await w.find('[data-test="schedule-form"]').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="schedule-form-error"]').text()).toContain('保存失败')
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('saves schedule settings → success toast', async () => {
    vi.mocked(api.saveScheduleSettings).mockResolvedValue({ ok: true, message: '排程设定已保存' })
    const w = mountPage()
    await flushPromises()
    await w.find('[data-test="schedule-form"]').trigger('submit')
    await flushPromises()
    expect(api.saveScheduleSettings).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })
})

describe('SettingsPage — W2 hydration-overwrite regression + dirty tracking', () => {
  it('REGRESSION: unsaved keyword-pool edits survive a query-data change that is NOT a window-focus refetch', async () => {
    const { wrapper: w, queryClient } = mountPageWithClient()
    await flushPromises()
    await w.find('textarea').setValue('unsaved-keyword-edit')

    // Simulate a refetch triggered by something other than window focus —
    // e.g. a cache invalidation fired from elsewhere in the app, or TanStack
    // re-delivering data after a background refetch. Before the W2 fix this
    // silently clobbered the textarea.
    queryClient.setQueryData(['settings', 'keywords'], {
      targets: ['https://x.com'],
      pools: { 'https://x.com': ['server', 'updated'] },
    })
    await flushPromises()

    expect((w.find('textarea').element as HTMLTextAreaElement).value).toBe(
      'unsaved-keyword-edit',
    )
  })

  it('REGRESSION: unsaved schedule edits survive a non-focus query-data change', async () => {
    const { wrapper: w, queryClient } = mountPageWithClient()
    await flushPromises()
    await w.find('#min-int').setValue('9')

    queryClient.setQueryData(['settings', 'schedule'], {
      min_interval_hours: 4,
      jitter_minutes: 30,
    })
    await flushPromises()

    expect((w.find('#min-int').element as HTMLInputElement).value).toBe('9')
  })

  it('marks the keyword-pool card dirty while editing, and clean again after a successful save', async () => {
    vi.mocked(api.saveKeywordPools).mockResolvedValue({ ok: true, message: 'ok' })
    const w = mountPage()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(false)

    await w.find('textarea').setValue('typing…')
    expect(dirtyStore.anyDirty).toBe(true)
    expect(dirtyStore.dirtyLabels).toContain('SEO 关键词池')

    await w.find('[data-test="keyword-form"]').trigger('submit')
    await flushPromises()
    expect(dirtyStore.anyDirty).toBe(false)
  })

  it('marks the schedule card dirty independently of the keyword-pool card', async () => {
    const w = mountPage()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()

    await w.find('#min-int').setValue('12')
    expect(dirtyStore.dirtyLabels).toEqual(['排程发布设定'])

    await w.find('textarea').setValue('also typing')
    expect(dirtyStore.dirtyLabels.slice().sort()).toEqual(
      ['排程发布设定', 'SEO 关键词池'].sort(),
    )
  })

  it('does not carry dirty state from a previous save into the next hydration round-trip', async () => {
    vi.mocked(api.saveScheduleSettings).mockResolvedValue({ ok: true, message: 'ok' })
    const { wrapper: w, queryClient } = mountPageWithClient()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()

    await w.find('#min-int').setValue('9')
    await w.find('[data-test="schedule-form"]').trigger('submit')
    await flushPromises()
    expect(dirtyStore.anyDirty).toBe(false)

    // A later, unrelated refetch (still not window-focus) should be allowed
    // through since nothing is dirty anymore.
    queryClient.setQueryData(['settings', 'schedule'], {
      min_interval_hours: 6,
      jitter_minutes: 15,
    })
    await flushPromises()
    expect((w.find('#min-int').element as HTMLInputElement).value).toBe('6')
    expect(dirtyStore.anyDirty).toBe(false)
  })
})
