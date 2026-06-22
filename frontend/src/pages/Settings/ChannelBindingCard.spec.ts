import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

vi.mock('../../api/settings', () => ({
  getChannelForms: vi.fn(),
  getChannels: vi.fn(),
  saveChannelCredential: vi.fn(),
  saveChannelToken: vi.fn(),
}))

import * as api from '../../api/settings'
import { ApiError } from '../../api/client'
import ChannelBindingCard from './ChannelBindingCard.vue'
import { useNotificationsStore } from '../../stores/notifications'

let pinia: ReturnType<typeof createPinia>

const TOKEN_FIELDS_FORM = {
  slug: 'wordpresscom',
  display_name: 'WordPress',
  auth_type: 'token_fields',
  supports_clear: true,
  save_via: 'credential',
  fields: [
    { name: 'token', label: 'Access Token', type: 'password', placeholder: '粘贴 token', help: '', secret: true },
    { name: 'site', label: 'Site URL', type: 'url', placeholder: 'https://x.wordpress.com', help: '站点地址', secret: false },
  ],
}

const TOKEN_PASTE_FORM = {
  slug: 'ghpages',
  display_name: 'GitHub Pages',
  auth_type: 'token_fields',
  supports_clear: true,
  save_via: 'token',
  fields: [
    { name: 'token', label: 'GitHub PAT', type: 'password', placeholder: 'ghp_...', help: '', secret: true },
  ],
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  vi.mocked(api.getChannelForms).mockResolvedValue({ forms: [TOKEN_FIELDS_FORM] })
  vi.mocked(api.getChannels).mockResolvedValue({ channels: [] })
})

function mountCard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ChannelBindingCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('ChannelBindingCard', () => {
  it('renders one binding form per channel with a field per schema entry', async () => {
    const w = mountCard()
    await flushPromises()
    const cards = w.findAll('[data-test="bind"]')
    expect(cards).toHaveLength(1)
    expect(cards[0].text()).toContain('WordPress')
    expect(cards[0].text()).toContain('未绑定')
    // password + url inputs rendered from the schema
    expect(w.find('input[type="password"]').exists()).toBe(true)
    expect(w.find('input[type="url"]').exists()).toBe(true)
  })

  it('submits the typed credential fields with auth_type, then clears secret inputs', async () => {
    vi.mocked(api.saveChannelCredential).mockResolvedValue({ ok: true, message: '已绑定 ✓' })
    const w = mountCard()
    await flushPromises()
    await w.find('input[type="password"]').setValue('sekret-token')
    await w.find('input[type="url"]').setValue('https://me.wordpress.com')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveChannelCredential).toHaveBeenCalledWith('wordpresscom', {
      auth_type: 'token_fields',
      token: 'sekret-token',
      site: 'https://me.wordpress.com',
    })
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
    // secret field is wiped after a successful save; non-secret is left intact
    expect((w.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
    expect((w.find('input[type="url"]').element as HTMLInputElement).value).toBe('https://me.wordpress.com')
  })

  it('offers a Clear button only when the channel is bound, posting clear=1', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [{
        slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
        bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
      }],
    })
    vi.mocked(api.saveChannelCredential).mockResolvedValue({ ok: true, message: '凭据已清除', cleared: true })
    const w = mountCard()
    await flushPromises()
    expect(w.text()).toContain('已绑定')
    const clearBtn = w.findAll('button').find((b) => b.text() === '清除')
    expect(clearBtn).toBeTruthy()
    await clearBtn!.trigger('click')
    await flushPromises()
    expect(api.saveChannelCredential).toHaveBeenCalledWith('wordpresscom', {
      auth_type: 'token_fields',
      clear: 1,
    })
  })

  it('surfaces a 422 credential rejection as a warning toast carrying the detail', async () => {
    vi.mocked(api.saveChannelCredential).mockRejectedValue(
      new ApiError('rejected', 422, { detail: 'site 必须以 https:// 开头' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('warning')
    expect(notify.toasts.at(-1)?.message).toContain('https://')
  })

  it('routes a save_via="token" channel (devto / ghpages) to the token-paste endpoint', async () => {
    vi.mocked(api.getChannelForms).mockResolvedValue({ forms: [TOKEN_PASTE_FORM] })
    vi.mocked(api.saveChannelToken).mockResolvedValue({ ok: true, message: 'ghpages token 已绑定 ✓' })
    const w = mountCard()
    await flushPromises()
    await w.find('input[type="password"]').setValue('ghp_secret')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(api.saveChannelToken).toHaveBeenCalledWith('ghpages', {
      auth_type: 'token_fields',
      token: 'ghp_secret',
    })
    expect(api.saveChannelCredential).not.toHaveBeenCalled()
    const notify = useNotificationsStore()
    expect(notify.toasts.at(-1)?.severity).toBe('success')
  })

  it('shows the empty state when no fixed-credential channels exist', async () => {
    vi.mocked(api.getChannelForms).mockResolvedValue({ forms: [] })
    const w = mountCard()
    await flushPromises()
    expect(w.find('[data-test="bind"]').exists()).toBe(false)
    expect(w.text()).toContain('无可直接填表绑定的渠道')
  })
})
