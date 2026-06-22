import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getBlogIds: vi.fn(),
  saveBlogIds: vi.fn(),
}))

import * as api from '../../api/settings'
import BlogIdsCard from './BlogIdsCard.vue'
import { useNotificationsStore } from '../../stores/notifications'

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
})
