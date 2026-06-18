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

  it('ready -> renders the default slot', () => {
    const w = mount(StateBlock, {
      props: { state: 'ready' },
      slots: { default: '<p>内容</p>' },
    })
    expect(w.html()).toContain('内容')
  })
})
