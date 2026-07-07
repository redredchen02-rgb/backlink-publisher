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
import { useSettingsDirtyStore } from '../../stores/settingsDirty'

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

function mountCardWithClient() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(ChannelBindingCard, {
    global: { plugins: [pinia, [VueQueryPlugin, { queryClient }]] },
  })
  return { wrapper, queryClient }
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

  it('defaults an unbound channel form to open and a bound channel form to collapsed', async () => {
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [{
        slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
        bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
      }],
    })
    const w = mountCard()
    await flushPromises()
    const details = w.find('[data-test="bind"]')
    expect((details.element as HTMLDetailsElement).open).toBe(false)
  })

  it('defaults an unbound channel form to open when no overview data exists yet', async () => {
    const w = mountCard()
    await flushPromises()
    const details = w.find('[data-test="bind"]')
    expect((details.element as HTMLDetailsElement).open).toBe(true)
  })

  it('groups forms into 未绑定 (first) and 已绑定 (second), each with role=group/aria-labelledby', async () => {
    vi.mocked(api.getChannelForms).mockResolvedValue({ forms: [TOKEN_FIELDS_FORM, TOKEN_PASTE_FORM] })
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [{
        slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
        bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
      }],
    })
    const w = mountCard()
    await flushPromises()
    expect(w.text()).toContain('未绑定 · 1')
    expect(w.text()).toContain('已绑定 · 1')
    const cards = w.findAll('[data-test="bind"]')
    expect(cards[0].text()).toContain('GitHub Pages') // unbound (ghpages), first
    expect(cards[1].text()).toContain('WordPress') // bound, second

    const groups = w.findAll('[role="group"]')
    expect(groups).toHaveLength(2)
    for (const g of groups) {
      const labelledBy = g.attributes('aria-labelledby')
      expect(labelledBy).toBeTruthy()
      expect(w.find(`#${labelledBy}`).exists()).toBe(true)
    }
  })

  it('shows only the 未绑定 group when every fixed-credential channel is unbound', async () => {
    const w = mountCard()
    await flushPromises()
    expect(w.text()).not.toContain('已绑定 ·')
    expect(w.text()).toContain('未绑定 · 1')
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

  it('post-save: a just-bound channel keeps its form open even after isBound() flips true', async () => {
    // Plan 2026-07-07-004 — the earlier design bound `<details open>` live to
    // isBound(), which would auto-collapse the form the user just filled in
    // the moment this invalidateQueries-triggered refetch resolved. openState
    // is seeded once and must not react to this.
    vi.mocked(api.getChannels)
      .mockResolvedValueOnce({ channels: [] })
      .mockResolvedValueOnce({
        channels: [{
          slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
          bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
        }],
      })
    vi.mocked(api.saveChannelCredential).mockResolvedValue({ ok: true, message: '已绑定 ✓' })
    const w = mountCard()
    await flushPromises()
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(true)

    await w.find('input[type="password"]').setValue('sekret-token')
    await w.find('input[type="url"]').setValue('https://me.wordpress.com')
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(w.text()).toContain('已绑定 ·')
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(true)
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

  it('a successful Clear reopens the form so the user can immediately re-enter credentials', async () => {
    // Code review (2026-07-07, adversarial + correctness): openState was
    // seeded collapsed back when this channel was bound and is never
    // recomputed from isBound() — without an explicit reopen on clear, the
    // channel would move to the 未绑定 group but stay visually collapsed,
    // hiding the very fields the user needs to fill in next.
    const BOUND = {
      slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
      bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
    }
    vi.mocked(api.getChannels)
      .mockResolvedValueOnce({ channels: [BOUND] })
      .mockResolvedValueOnce({ channels: [{ ...BOUND, bound: false, identity: null }] })
    vi.mocked(api.saveChannelCredential).mockResolvedValue({ ok: true, message: '凭据已清除', cleared: true })
    const w = mountCard()
    await flushPromises()
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(false)

    const clearBtn = w.findAll('button').find((b) => b.text() === '清除')
    await clearBtn!.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('未绑定 ·')
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(true)
  })

  it('seeds openState from the true bound status even when overviewQuery resolves after formsQuery (cold-load race)', async () => {
    // Code review (2026-07-07, julik-frontend-races): formsQuery and
    // overviewQuery are two independent requests with no ordering guarantee.
    // Seeding openState the moment forms resolves — before overview has ever
    // resolved — would read an empty boundMap and treat every channel as
    // unbound, permanently seeding an already-bound channel's form open
    // (seeding never re-runs) even though R3 says bound channels default
    // collapsed.
    let resolveChannels!: (v: Awaited<ReturnType<typeof api.getChannels>>) => void
    vi.mocked(api.getChannels).mockReturnValue(
      new Promise((resolve) => { resolveChannels = resolve }),
    )
    const w = mountCard()
    await flushPromises() // formsQuery resolves; overviewQuery still pending

    // Must not have guessed "unbound" (open) while the true status is unknown.
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(false)

    resolveChannels({
      channels: [{
        slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
        bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
      }],
    })
    await flushPromises()

    expect(w.text()).toContain('已绑定 ·')
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(false)
  })

  it('W6: a 422 credential rejection renders inline under that slug, not a global toast', async () => {
    vi.mocked(api.saveChannelCredential).mockRejectedValue(
      new ApiError('rejected', 422, { detail: 'site 必须以 https:// 开头' }),
    )
    const w = mountCard()
    await flushPromises()
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test="bind-error-wordpresscom"]').text()).toContain('https://')
    const notify = useNotificationsStore()
    expect(notify.toasts).toHaveLength(0)
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

  it('marks the card dirty while editing and clean again after a successful save (W2)', async () => {
    vi.mocked(api.saveChannelCredential).mockResolvedValue({ ok: true, message: 'ok' })
    const w = mountCard()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(false)

    await w.find('input[type="url"]').setValue('https://me.wordpress.com')
    expect(dirtyStore.anyDirty).toBe(true)
    expect(dirtyStore.dirtyLabels).toContain('渠道凭据绑定')

    await w.find('form').trigger('submit')
    await flushPromises()
    expect(dirtyStore.anyDirty).toBe(false)
  })

  it('W2: a newly-appearing channel form does not itself count as a dirty edit, and lands in the correct group', async () => {
    // Regression guard for the incremental-baseline design (see the card's
    // own comment): seeding a brand-new slug's blank defaults into `edits`
    // (as happens whenever formsQuery re-resolves with an extra channel) must
    // not be mistaken for a user edit. wordpresscom is bound so the streamed-
    // in ghpages (unbound) form's group placement is actually distinguishable
    // (plan 2026-07-07-004 Unit 2 test scenario).
    vi.mocked(api.getChannels).mockResolvedValue({
      channels: [{
        slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
        bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
      }],
    })
    const { wrapper: w, queryClient } = mountCardWithClient()
    await flushPromises()
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(false)

    // Simulate a second channel becoming available mid-session (a refetch
    // elsewhere delivering an extra form) — no user input happened.
    queryClient.setQueryData(['settings', 'channel-forms'], {
      forms: [TOKEN_FIELDS_FORM, TOKEN_PASTE_FORM],
    })
    await flushPromises()

    expect(w.findAll('[data-test="bind"]')).toHaveLength(2)
    expect(w.text()).toContain('未绑定 · 1')
    expect(w.text()).toContain('已绑定 · 1')
    const cards = w.findAll('[data-test="bind"]')
    expect(cards[0].text()).toContain('GitHub Pages') // unbound (ghpages), first group
    expect(cards[1].text()).toContain('WordPress') // bound, second group
    expect(dirtyStore.anyDirty).toBe(false)
  })

  it('W2: an unsaved field edit is untouched when a new channel form streams in', async () => {
    const { wrapper: w, queryClient } = mountCardWithClient()
    await flushPromises()
    await w.find('input[type="password"]').setValue('typed-token')

    queryClient.setQueryData(['settings', 'channel-forms'], {
      forms: [TOKEN_FIELDS_FORM, TOKEN_PASTE_FORM],
    })
    await flushPromises()

    expect((w.find('input[type="password"]').element as HTMLInputElement).value).toBe(
      'typed-token',
    )
    const dirtyStore = useSettingsDirtyStore()
    expect(dirtyStore.anyDirty).toBe(true)
  })

  it('a channel moving groups when the overview query resolves late keeps its open state and unsaved edits', async () => {
    const { wrapper: w, queryClient } = mountCardWithClient()
    await flushPromises()
    // No overview data yet → treated as unbound → open by default.
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(true)
    await w.find('input[type="password"]').setValue('typed-token')

    // Overview query resolves later, revealing the channel is actually bound.
    queryClient.setQueryData(['settings', 'channels'], {
      channels: [{
        slug: 'wordpresscom', display_name: 'WordPress', auth_type: 'token_fields',
        bound: true, identity: 'me@blog', dofollow: true, last_verify_result: 'ok', blockers: [],
      }],
    })
    await flushPromises()

    expect(w.text()).toContain('已绑定 ·')
    expect((w.find('[data-test="bind"]').element as HTMLDetailsElement).open).toBe(true)
    expect((w.find('input[type="password"]').element as HTMLInputElement).value).toBe('typed-token')
  })
})
