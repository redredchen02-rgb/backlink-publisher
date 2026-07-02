import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flashTypeToSeverity, useNotificationsStore } from './notifications'

beforeEach(() => setActivePinia(createPinia()))

describe('flashTypeToSeverity', () => {
  it('maps the legacy flash_type vocabulary', () => {
    expect(flashTypeToSeverity('success')).toBe('success')
    expect(flashTypeToSeverity('danger')).toBe('error')
    expect(flashTypeToSeverity('error')).toBe('error')
    expect(flashTypeToSeverity('warning')).toBe('warning')
    expect(flashTypeToSeverity('whatever')).toBe('info')
    expect(flashTypeToSeverity(null)).toBe('info')
  })
})

describe('notifications store', () => {
  it('push adds a toast; errors are sticky (timeout 0)', () => {
    const s = useNotificationsStore()
    const id = s.push('hi', 'success')
    expect(s.toasts.length).toBe(1)
    expect(s.toasts[0].id).toBe(id)
    const eid = s.push('boom', 'error')
    expect(s.toasts.find((t) => t.id === eid)!.timeout).toBe(0)
  })

  it('push carries an optional reportId through, sticky by default when paired with severity error (Plan U7)', () => {
    const s = useNotificationsStore()
    const id = s.push('抓到一个错误', 'error', undefined, 'a1b2c3d4-0000-4000-8000-000000000042')
    const t = s.toasts.find((x) => x.id === id)!
    expect(t.reportId).toBe('a1b2c3d4-0000-4000-8000-000000000042')
    expect(t.timeout).toBe(0)
  })

  it('regression: a toast pushed without a reportId leaves the field undefined and keeps its ordinary timeout', () => {
    const s = useNotificationsStore()
    const id = s.push('ordinary toast', 'success')
    const t = s.toasts.find((x) => x.id === id)!
    expect(t.reportId).toBeUndefined()
    expect(t.timeout).toBe(4000)
  })

  it('dismiss removes one; clear removes all', () => {
    const s = useNotificationsStore()
    const id = s.push('a')
    s.push('b')
    s.dismiss(id)
    expect(s.toasts.length).toBe(1)
    s.clear()
    expect(s.toasts.length).toBe(0)
  })

  it('pushFlash bridges a legacy payload; empty message -> null', () => {
    const s = useNotificationsStore()
    expect(s.pushFlash('', 'success')).toBeNull()
    s.pushFlash('已保存', 'success')
    expect(s.toasts[0].severity).toBe('success')
    expect(s.toasts[0].message).toBe('已保存')
  })
})
