import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useErrorToast } from './useErrorToast'
import { useNotificationsStore } from '../stores/notifications'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useErrorToast', () => {
  it('classifies error and pushes fixed-template message — never raw server text', () => {
    const { toastError } = useErrorToast()
    toastError({ status: 500, error: 'raw server error <script>' })
    const store = useNotificationsStore()
    expect(store.toasts).toHaveLength(1)
    expect(store.toasts[0].severity).toBe('error')
    // Must contain the fixed classifyError title, not raw server content
    expect(store.toasts[0].message).toContain('服务器出错了')
    expect(store.toasts[0].message).not.toContain('raw server error')
    expect(store.toasts[0].message).not.toContain('<script>')
  })

  it('network failure maps to fixed network-error template', () => {
    const { toastError } = useErrorToast()
    toastError(new TypeError('Failed to fetch'))
    const store = useNotificationsStore()
    expect(store.toasts[0].severity).toBe('error')
    // classifyError maps fetch failures to a network template
    expect(store.toasts[0].message).toBeTruthy()
    expect(store.toasts[0].message).not.toContain('Failed to fetch')
  })

  it('error toast is always sticky (timeout = 0)', () => {
    const { toastError } = useErrorToast()
    toastError({ status: 403 })
    const store = useNotificationsStore()
    expect(store.toasts[0].timeout).toBe(0)
  })
})
