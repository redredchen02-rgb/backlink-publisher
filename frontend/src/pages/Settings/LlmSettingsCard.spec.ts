import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getLlmConfig: vi.fn(),
  saveLlmConfig: vi.fn(),
  clearLlmConfig: vi.fn(),
  testLlmConnection: vi.fn(),
  testLlmGeneration: vi.fn(),
  testImageGen: vi.fn(),
  generateImageSample: vi.fn(),
}))

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import LlmSettingsCard from './LlmSettingsCard.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useSettingsDirtyStore } from '../../stores/settingsDirty'

const CONFIG = {
  endpoint: 'https://api.openai.com/v1',
  model: 'gpt-4o',
  temperature: 0.7,
  system_prompt: '',
  article_system_prompt: '',
  use_article_gen: false,
  use_image_gen: false,
  image_gen_endpoint: '',
  image_gen_model: '',
  image_gen_banner_size: '1200x630',
  has_api_key: true,
  has_image_gen_api_key: false,
}

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getLlmConfig).mockResolvedValue({ ...CONFIG })
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(LlmSettingsCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

function mountCardWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(LlmSettingsCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
  return { wrapper, queryClient }
}

describe('LlmSettingsCard', () => {
  it('hydrates endpoint/model and shows the "已设置" placeholder when a key is stored', async () => {
    const w = mountCard()
    await flushPromises()
    expect((w.find('#llm-ep').element as HTMLInputElement).value).toBe('https://api.openai.com/v1')
    expect((w.find('#llm-model').element as HTMLInputElement).value).toBe('gpt-4o')
    expect((w.find('#llm-key').element as HTMLInputElement).placeholder).toContain('已设置')
    // the secret input itself is blank (never hydrated)
    expect((w.find('#llm-key').element as HTMLInputElement).value).toBe('')
  })

  it('saves config → success toast and clears the secret input', async () => {
    vi.mocked(api.saveLlmConfig).mockResolvedValue({ ok: true, message: 'LLM 设定已保存' })
    const w = mountCard()
    await flushPromises()
    await w.find('#llm-key').setValue('sk-new-secret')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveLlmConfig).toHaveBeenCalledWith(
      expect.objectContaining({ endpoint: 'https://api.openai.com/v1', api_key: 'sk-new-secret' }),
    )
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
    expect((w.find('#llm-key').element as HTMLInputElement).value).toBe('')
  })

  it('W6: a 422 mentioning Endpoint renders inline under that field, not a toast', async () => {
    vi.mocked(api.saveLlmConfig).mockRejectedValue(
      new ApiError('rejected', 422, { detail: 'Endpoint 必须以 https:// 开头' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="err-endpoint"]').text()).toContain('https')
    expect(w.find('[data-test="llm-form-error"]').exists()).toBe(false)
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('W6: a 422 mentioning image_gen_endpoint attributes to the image-gen field, not the plain endpoint one', async () => {
    vi.mocked(api.saveLlmConfig).mockRejectedValue(
      new ApiError('rejected', 422, { detail: 'image_gen_endpoint 必须以 https:// 开头' }),
    )
    const w = mountCard()
    await flushPromises()
    // the image-gen fields only render once the feature toggle is on
    const toggles = w.findAll('.switch input[type="checkbox"]')
    await toggles[1].setValue(true)
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="err-img-ep"]').exists()).toBe(true)
    expect(w.find('[data-test="err-endpoint"]').exists()).toBe(false)
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('renders the connection probe result inline (ok → 连接成功 + model count)', async () => {
    vi.mocked(api.testLlmConnection).mockResolvedValue({
      status: 'ok',
      message: '连接成功！',
      models: ['gpt-4o', 'gpt-4o-mini'],
    })
    const w = mountCard()
    await flushPromises()
    await w.find('.diag button').trigger('click')
    await flushPromises()
    const txt = w.find('.diag__r').text()
    expect(txt).toContain('连接成功')
    expect(txt).toContain('2 个模型')
  })

  it('clears the config → success toast', async () => {
    vi.mocked(api.clearLlmConfig).mockResolvedValue({ ok: true, message: 'LLM 配置已清除' })
    const w = mountCard()
    await flushPromises()
    await w.find('.actions .danger').trigger('click')
    await flushPromises()
    expect(api.clearLlmConfig).toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('REGRESSION (W2): an unsaved endpoint edit survives a non-focus query-data change', async () => {
    const { wrapper: w, queryClient } = mountCardWithClient()
    await flushPromises()
    await w.find('#llm-ep').setValue('https://typed.example.com/v1')

    queryClient.setQueryData(['settings', 'llm'], { ...CONFIG, endpoint: 'https://server-changed.example.com/v1' })
    await flushPromises()

    expect((w.find('#llm-ep').element as HTMLInputElement).value).toBe(
      'https://typed.example.com/v1',
    )
  })

  it('marks the card dirty while editing and clean again after a successful save', async () => {
    vi.mocked(api.saveLlmConfig).mockResolvedValue({ ok: true, message: 'ok' })
    const w = mountCard()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(false)

    await w.find('#llm-model').setValue('gpt-4.1')
    expect(dirtyStore.anyDirty).toBe(true)
    expect(dirtyStore.dirtyLabels).toContain('进阶 LLM 整合')

    await w.find('form').trigger('submit')
    await flushPromises()
    expect(dirtyStore.anyDirty).toBe(false)
  })
})
