import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getBlogIds: vi.fn(),
  saveBlogIds: vi.fn(),
}))

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import BlogIdsCard from './BlogIdsCard.vue'
import { useNotificationsStore } from '../../stores/notifications'
import { useSettingsDirtyStore } from '../../stores/settingsDirty'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getBlogIds).mockResolvedValue({ blog_ids: {} })
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(BlogIdsCard, { global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] } })
}

function mountCardWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(BlogIdsCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
  return { wrapper, queryClient }
}

function btn(w: ReturnType<typeof mountCard>, text: string) {
  return w.findAll('button').find((b) => b.text() === text)
}

describe('BlogIdsCard', () => {
  it('hydrates one row per existing mapping entry', async () => {
    vi.mocked(api.getBlogIds).mockResolvedValue({
      blog_ids: { 'https://a.com': '111', 'https://b.com': '222' },
    })
    const w = mountCard()
    await flushPromises()
    const inputs = w.findAll('[data-test="blogid-row"] input')
    expect(w.findAll('[data-test="blogid-row"]')).toHaveLength(2)
    expect((inputs[0].element as HTMLInputElement).value).toBe('https://a.com')
    expect((inputs[1].element as HTMLInputElement).value).toBe('111')
  })

  it('shows a single blank row when the mapping is empty', async () => {
    const w = mountCard()
    await flushPromises()
    expect(w.findAll('[data-test="blogid-row"]')).toHaveLength(1)
  })

  it('adds and removes rows', async () => {
    const w = mountCard()
    await flushPromises()
    await btn(w, '新增一行')!.trigger('click')
    expect(w.findAll('[data-test="blogid-row"]')).toHaveLength(2)
    await w.find('[aria-label="删除此行"]').trigger('click')
    expect(w.findAll('[data-test="blogid-row"]')).toHaveLength(1)
  })

  it('saves the typed rows as a mapping (success toast), then refetches', async () => {
    vi.mocked(api.saveBlogIds).mockResolvedValue({ ok: true, message: 'Blog ID 映射已保存' })
    const w = mountCard()
    await flushPromises()
    const inputs = w.findAll('[data-test="blogid-row"] input')
    await inputs[0].setValue('https://x.com')
    await inputs[1].setValue('98765')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveBlogIds).toHaveBeenCalledWith({ 'https://x.com': '98765' })
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('drops blank/half-filled rows from the submitted mapping', async () => {
    vi.mocked(api.saveBlogIds).mockResolvedValue({ ok: true, message: '保存' })
    const w = mountCard()
    await flushPromises()
    // row 0: complete; row 1: domain only (no id) — must be dropped
    const inputs0 = w.findAll('[data-test="blogid-row"] input')
    await inputs0[0].setValue('https://a.com')
    await inputs0[1].setValue('111')
    await btn(w, '新增一行')!.trigger('click')
    const inputs1 = w.findAll('[data-test="blogid-row"] input')
    await inputs1[2].setValue('https://incomplete.com')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveBlogIds).toHaveBeenCalledWith({ 'https://a.com': '111' })
  })

  it('REGRESSION (W2): an unsaved row edit survives a non-focus query-data change', async () => {
    vi.mocked(api.getBlogIds).mockResolvedValue({ blog_ids: { 'https://a.com': '111' } })
    const { wrapper: w, queryClient } = mountCardWithClient()
    await flushPromises()
    const inputs = w.findAll('[data-test="blogid-row"] input')
    await inputs[1].setValue('typed-999')

    queryClient.setQueryData(['settings', 'blog-ids'], {
      blog_ids: { 'https://a.com': 'server-777' },
    })
    await flushPromises()

    const after = w.findAll('[data-test="blogid-row"] input')
    expect((after[1].element as HTMLInputElement).value).toBe('typed-999')
  })

  it('W6: 422 renders an inline form error, not a global toast', async () => {
    vi.mocked(api.saveBlogIds).mockRejectedValue(
      new ApiError('rejected', 422, { detail: '域名格式无效' }),
    )
    const w = mountCard()
    await flushPromises()
    const inputs = w.findAll('[data-test="blogid-row"] input')
    await inputs[0].setValue('not-a-url')
    await inputs[1].setValue('111')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="blogids-form-error"]').text()).toBe('域名格式无效')
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
  })

  it('W6: the submit button is busy only while its own save is in flight', async () => {
    let resolveSave: (v: { ok: boolean; message: string }) => void = () => {}
    vi.mocked(api.saveBlogIds).mockReturnValue(
      new Promise((resolve) => {
        resolveSave = resolve
      }),
    )
    const w = mountCard()
    await flushPromises()
    const inputs = w.findAll('[data-test="blogid-row"] input')
    await inputs[0].setValue('https://a.com')
    await inputs[1].setValue('111')
    await w.find('form').trigger('submit')
    await flushPromises()
    const submitBtn = w.findAll('button').find((b) => b.text().includes('保存中'))
    expect(submitBtn?.attributes('disabled')).toBeDefined()
    resolveSave({ ok: true, message: '保存' })
    await flushPromises()
  })

  it('marks the card dirty while editing and clean again after a successful save', async () => {
    vi.mocked(api.saveBlogIds).mockResolvedValue({ ok: true, message: 'ok' })
    const w = mountCard()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(false)

    const inputs = w.findAll('[data-test="blogid-row"] input')
    await inputs[0].setValue('https://x.com')
    expect(dirtyStore.anyDirty).toBe(true)
    expect(dirtyStore.dirtyLabels).toContain('Blogger Blog ID 映射')

    await inputs[1].setValue('999')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(dirtyStore.anyDirty).toBe(false)
  })
})
