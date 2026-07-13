import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBadge from '../components/StatusBadge.vue'

describe('StatusBadge v2', () => {
  it('maps known status to tone class and zh text', () => {
    const w = mount(StatusBadge, { props: { status: 'running' } })
    expect(w.classes()).toContain('badge--primary')
    expect(w.text()).toBe('进行中')
  })

  it('supports new statuses added for page migrations', () => {
    for (const [status, tone] of [
      ['won', 'success'], ['lost', 'danger'], ['sent', 'primary'], ['draft', 'info'],
      ['open', 'danger'], ['acknowledged', 'warning'], ['resolved', 'success'],
      ['scheduled', 'info'], ['deleted', 'dark'],
    ] as const) {
      const w = mount(StatusBadge, { props: { status } })
      expect(w.classes(), status).toContain(`badge--${tone}`)
    }
  })

  it('tone prop overrides status mapping', () => {
    const w = mount(StatusBadge, { props: { tone: 'success', label: '存活' } })
    expect(w.classes()).toContain('badge--success')
    expect(w.text()).toBe('存活')
  })

  it('falls back to neutral for unknown status', () => {
    const w = mount(StatusBadge, { props: { status: 'weird_thing' } })
    expect(w.classes()).toContain('badge--neutral')
    expect(w.text()).toBe('weird_thing')
  })

  it('is reactive to status changes after mount', async () => {
    const w = mount(StatusBadge, { props: { status: 'pending' } })
    expect(w.classes()).toContain('badge--neutral')
    await w.setProps({ status: 'success' })
    expect(w.classes()).toContain('badge--success')
    expect(w.text()).toBe('成功')
  })

  it('never emits legacy Bootstrap classes', () => {
    const w = mount(StatusBadge, { props: { status: 'success' } })
    expect(w.classes().join(' ')).not.toMatch(/\bbg-/)
  })
})
