// Plan 2026-07-06-005 W2 — route-leave guard + beforeunload protection.
//
// Imports the real router singleton (not a stub) so both the `beforeEach`
// guard and the `beforeunload` listener it installs at module-load time are
// under test exactly as main.ts wires them (this file never touches
// main.ts). Pinia is (re)activated per test so `useSettingsDirtyStore()`
// inside the guard/listener always resolves against a fresh, isolated store.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { router } from './index'
import { useSettingsDirtyStore } from '../stores/settingsDirty'

describe('router — W2 settings dirty route-leave guard', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    await router.push('/settings')
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('allows navigation without prompting when nothing is dirty', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    await router.push('/history')
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(router.currentRoute.value.path).toBe('/history')
  })

  it('prompts and blocks navigation when a card is dirty and the operator cancels', async () => {
    const store = useSettingsDirtyStore()
    store.setDirty('settings-keywords', 'SEO 关键词池')
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    await router.push('/history')

    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(confirmSpy.mock.calls[0][0]).toContain('SEO 关键词池')
    // navigation was aborted — still on /settings, content (i.e. dirty state) intact
    expect(router.currentRoute.value.path).toBe('/settings')
    expect(store.anyDirty).toBe(true)
  })

  it('proceeds and clears every dirty card when the operator confirms leaving', async () => {
    const store = useSettingsDirtyStore()
    store.setDirty('settings-blogger', 'Blogger')
    store.setDirty('settings-notion', 'Notion')
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    await router.push('/history')

    expect(router.currentRoute.value.path).toBe('/history')
    expect(store.anyDirty).toBe(false)
  })

  it('lists only the currently-dirty cards (a saved card does not appear)', async () => {
    const store = useSettingsDirtyStore()
    store.setDirty('settings-blogids', 'Blogger Blog ID 映射')
    store.setDirty('settings-llm', '进阶 LLM 整合')
    store.clearDirty('settings-llm') // simulates card B having been saved already
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    await router.push('/history')

    const message = confirmSpy.mock.calls[0][0] as string
    expect(message).toContain('Blogger Blog ID 映射')
    expect(message).not.toContain('进阶 LLM 整合')
  })

  it('does not intercept navigating to the same route', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const store = useSettingsDirtyStore()
    store.setDirty('settings-keywords', 'SEO 关键词池')

    await router.push('/settings')

    expect(confirmSpy).not.toHaveBeenCalled()
  })
})

describe('router — W2 beforeunload tab-close protection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('calls preventDefault (and sets returnValue) when a card is dirty', () => {
    const store = useSettingsDirtyStore()
    store.setDirty('settings-llm', '进阶 LLM 整合')

    const event = new Event('beforeunload', { cancelable: true })
    const preventSpy = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)

    expect(preventSpy).toHaveBeenCalled()
  })

  it('does nothing when nothing is dirty', () => {
    const event = new Event('beforeunload', { cancelable: true })
    const preventSpy = vi.spyOn(event, 'preventDefault')
    window.dispatchEvent(event)

    expect(preventSpy).not.toHaveBeenCalled()
  })
})
