import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import Toast from './Toast.vue'
import { useNotificationsStore } from '../stores/notifications'
import { useReportPanelStore } from '../stores/reportPanel'

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('Toast', () => {
  it('renders store toasts in an aria-live region and dismisses them', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    const store = useNotificationsStore()

    store.push('hello', 'success')
    await w.vm.$nextTick()
    // Dual live-region structure: one assertive (errors) + one polite (others)
    expect(w.find('[aria-live="assertive"]').exists()).toBe(true)
    expect(w.find('[aria-live="polite"]').exists()).toBe(true)
    expect(w.text()).toContain('hello')

    await w.find('.toast__close').trigger('click')
    await w.vm.$nextTick()
    expect(w.text()).not.toContain('hello')
  })

  it('error toasts use role=alert', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('boom', 'error')
    await w.vm.$nextTick()
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('success toast routes to polite region, NOT assertive', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('saved!', 'success')
    await w.vm.$nextTick()
    expect(w.find('[aria-live="polite"]').text()).toContain('saved!')
    expect(w.find('[aria-live="assertive"]').text()).not.toContain('saved!')
  })

  it('error toast routes to assertive region, NOT polite', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('failed!', 'error')
    await w.vm.$nextTick()
    expect(w.find('[aria-live="assertive"]').text()).toContain('failed!')
    expect(w.find('[aria-live="polite"]').text()).not.toContain('failed!')
  })
})

describe('Toast — "补充说明" action (Plan U7)', () => {
  it('a toast carrying reportId shows the "补充说明" action and opens the shared panel with that id', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('抓到一个错误', 'error', 0, 'b2c3d4e5-0000-4000-8000-000000000099')
    await w.vm.$nextTick()

    const btn = w.find('.toast__detail')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')

    const panel = useReportPanelStore()
    expect(panel.isOpen).toBe(true)
    expect(panel.reportId).toBe('b2c3d4e5-0000-4000-8000-000000000099')
  })

  it('paired: a toast with no reportId does NOT show the "补充说明" action', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('boom', 'error')
    await w.vm.$nextTick()

    expect(w.find('.toast__detail').exists()).toBe(false)
  })

  it('regression: with reportId absent, existing toast rendering (message + close button) is unchanged', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('hello again', 'success')
    await w.vm.$nextTick()

    expect(w.text()).toContain('hello again')
    expect(w.find('.toast__close').exists()).toBe(true)
    expect(w.find('.toast__detail').exists()).toBe(false)
  })
})

describe('Toast — reportId toasts stay sticky (Plan U7 regression guard)', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('a reportId-bearing (severity error) toast does not auto-dismiss', async () => {
    vi.useFakeTimers()
    const w = mount(Toast, { global: { plugins: [pinia] } })
    const store = useNotificationsStore()
    store.push('抓到一个错误', 'error', 0, 'c3d4e5f6-0000-4000-8000-000000000007')
    await w.vm.$nextTick()

    vi.advanceTimersByTime(60_000)
    await w.vm.$nextTick()

    expect(store.toasts.length).toBe(1)
    expect(w.text()).toContain('抓到一个错误')
  })

  it('paired: an ordinary (no reportId) toast keeps its existing auto-dismiss timeout', async () => {
    vi.useFakeTimers()
    const w = mount(Toast, { global: { plugins: [pinia] } })
    const store = useNotificationsStore()
    store.push('will auto-dismiss', 'success')
    await w.vm.$nextTick()

    vi.advanceTimersByTime(4_000)
    await w.vm.$nextTick()

    expect(store.toasts.length).toBe(0)
    expect(w.text()).not.toContain('will auto-dismiss')
  })
})

describe('Toast — undo action (Plan 2026-07-06-004 Unit 6)', () => {
  it('a toast carrying undoAction shows a button with its label and fires onClick', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    const store = useNotificationsStore()
    const onClick = vi.fn()
    store.push('已标记为已解决', 'success', 6000, undefined, { label: '撤销', onClick })
    await w.vm.$nextTick()

    const btn = w.find('.toast__undo')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toBe('撤销')
    await btn.trigger('click')
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('paired: a toast with no undoAction does NOT show the undo button', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    useNotificationsStore().push('ordinary toast', 'success')
    await w.vm.$nextTick()

    expect(w.find('.toast__undo').exists()).toBe(false)
  })

  it('an error-severity toast can carry undoAction too (assertive region)', async () => {
    const w = mount(Toast, { global: { plugins: [pinia] } })
    const onClick = vi.fn()
    useNotificationsStore().push('撤销失败：boom', 'error', 0, undefined, { label: '重试', onClick })
    await w.vm.$nextTick()

    const region = w.find('[aria-live="assertive"]')
    const btn = region.find('.toast__undo')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
