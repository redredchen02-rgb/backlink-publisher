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

  it('surfaces a 422 save rejection as a warning toast carrying the detail', async () => {
    vi.mocked(api.saveLlmConfig).mockRejectedValue(
      new ApiError('rejected', 422, { detail: 'LLM Endpoint 必须是 https://' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
    expect(notify.toasts.at(-1)?.message).toContain('https')
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
})
