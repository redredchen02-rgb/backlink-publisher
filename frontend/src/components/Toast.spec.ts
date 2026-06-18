import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import Toast from './Toast.vue'
import { useNotificationsStore } from '../stores/notifications'

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
    expect(w.find('[role="region"][aria-label="通知"]').exists()).toBe(true)
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
})
