import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../api/profiles', () => ({
  getProfiles: vi.fn(),
  saveProfile: vi.fn(),
  deleteProfile: vi.fn(),
}))

import * as api from '../api/profiles'
import ProfileSelector from './ProfileSelector.vue'
import { useNotificationsStore } from '../stores/notifications'

const PROFILE = {
  name: 'preset-a',
  platform: 'medium',
  language: 'en-US',
  url_mode: 'C',
  publish_mode: 'draft',
}
const CURRENT = { platform: 'blogger', language: 'zh-CN', publishMode: 'publish' }

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getProfiles).mockResolvedValue({ items: [PROFILE] })
})

function mountSelector(current = CURRENT) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ProfileSelector, {
    props: { current },
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('ProfileSelector', () => {
  it('renders the saved profiles in the select', async () => {
    const w = mountSelector()
    await flushPromises()
    const opts = w.findAll('option').map((o) => o.text())
    expect(opts).toContain('preset-a')
  })

  it('emits apply with the chosen profile on load', async () => {
    const w = mountSelector()
    await flushPromises()
    await w.find('select').setValue('preset-a')
    await w.findAll('button').find((b) => b.text() === '载入')!.trigger('click')
    expect(w.emitted('apply')?.[0]?.[0]).toMatchObject({ name: 'preset-a', platform: 'medium' })
  })

  it('saves the current config under the typed name (url_mode omitted → backend default)', async () => {
    vi.mocked(api.saveProfile).mockResolvedValue({ items: [PROFILE] })
    const w = mountSelector()
    await flushPromises()
    await w.find('input[type="text"]').setValue('preset-b')
    await w.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(api.saveProfile).toHaveBeenCalledWith({
      name: 'preset-b',
      platform: 'blogger',
      language: 'zh-CN',
      publish_mode: 'publish',
    })
  })

  it('warns and does not call the API when saving with a blank name', async () => {
    const w = mountSelector()
    await flushPromises()
    await w.findAll('button').find((b) => b.text() === '保存')!.trigger('click')
    expect(api.saveProfile).not.toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
  })

  it('deletes the selected profile', async () => {
    vi.mocked(api.deleteProfile).mockResolvedValue({ items: [] })
    const w = mountSelector()
    await flushPromises()
    await w.find('select').setValue('preset-a')
    await w.findAll('button').find((b) => b.text() === '删除')!.trigger('click')
    await flushPromises()
    expect(api.deleteProfile).toHaveBeenCalledWith('preset-a')
  })
})
