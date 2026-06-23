import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StateBlock from './StateBlock.vue'

describe('StateBlock four-state matrix', () => {
  it('loading -> skeletons + aria-busy', () => {
    const w = mount(StateBlock, { props: { state: 'loading' } })
    expect(w.find('[aria-busy="true"]').exists()).toBe(true)
    expect(w.findAll('.skeleton').length).toBeGreaterThan(0)
  })

  it('empty -> empty text', () => {
    const w = mount(StateBlock, { props: { state: 'empty', emptyText: '空空如也' } })
    expect(w.text()).toContain('空空如也')
  })

  it('error -> classifyError taxonomy title + retry emits', async () => {
    const w = mount(StateBlock, { props: { state: 'error', error: { status: 500 } } })
    expect(w.text()).toContain('服务器出错了') // fixed template, not raw text
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toBeTruthy()
  })

  it('error -> retryable=false hides retry button', () => {
    const w = mount(StateBlock, { props: { state: 'error', error: { status: 500 }, retryable: false } })
    expect(w.find('button').exists()).toBe(false)
  })

  it('ready -> renders the default slot', () => {
    const w = mount(StateBlock, {
      props: { state: 'ready' },
      slots: { default: '<p>内容</p>' },
    })
    expect(w.html()).toContain('内容')
  })
})

describe('StateBlock stalebar', () => {
  it('isFetching=true shows pulse and "更新中" text', () => {
    const w = mount(StateBlock, {
      props: { state: 'ready', isFetching: true },
      slots: { default: '<p>data</p>' },
    })
    expect(w.find('.state__stalebar').exists()).toBe(true)
    expect(w.find('.state__pulse').exists()).toBe(true)
    expect(w.text()).toContain('更新中')
  })

  it('stale=true + lastUpdated shows relative timestamp', () => {
    const pastIso = new Date(Date.now() - 90_000).toISOString() // 90 s ago
    const w = mount(StateBlock, {
      props: { state: 'ready', stale: true, lastUpdated: pastIso },
      slots: { default: '<p>data</p>' },
    })
    expect(w.find('.state__stalebar').text()).toContain('分钟前')
    expect(w.find('.state__pulse').exists()).toBe(false)
  })

  it('stale=true without lastUpdated shows fallback text', () => {
    const w = mount(StateBlock, {
      props: { state: 'ready', stale: true },
      slots: { default: '<p>data</p>' },
    })
    expect(w.find('.state__stalebar').text()).toContain('数据可能不是最新')
  })

  it('stalebar is always in DOM (static aria-live container)', () => {
    const w = mount(StateBlock, {
      props: { state: 'ready' },
      slots: { default: '<p>data</p>' },
    })
    // aria-live container must exist before content arrives for SR to register it
    expect(w.find('[aria-live="polite"]').exists()).toBe(true)
    expect(w.find('.state__stalebar').exists()).toBe(true)
    // but it is visually empty when neither isFetching nor stale
    expect(w.find('.state__stalebar').text()).toBe('')
  })

  it('stalebar does NOT appear in loading/error/empty states', () => {
    for (const state of ['loading', 'empty', 'error'] as const) {
      const w = mount(StateBlock, {
        props: { state, isFetching: true, stale: true, error: { status: 500 } },
      })
      expect(w.find('.state__stalebar').exists()).toBe(false)
    }
  })
})
