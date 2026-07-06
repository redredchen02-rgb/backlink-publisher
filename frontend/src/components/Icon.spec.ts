// Icon — Plan 2026-07-06-005 W7 (R7 / D9) coverage.
//
// Covers:
//  - 已知 name 渲染 inline SVG(path 数据、1em 尺寸、currentColor)
//  - 未知 name:console.warn 一次 + 渲染为空(不抛错)
//  - a11y 默认:装饰性 aria-hidden="true"、无 role/aria-label
//  - label 模式:role="img" + aria-label,且不再 aria-hidden
//  - class 透传(attrs fallthrough 到 svg 根节点)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import Icon from './Icon.vue'

describe('Icon', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    warnSpy.mockRestore()
  })

  it('已知 name 渲染 inline SVG,1em 尺寸 + currentColor', () => {
    const wrapper = mount(Icon, { props: { name: 'shield-check' } })
    const svg = wrapper.find('svg')
    expect(svg.exists()).toBe(true)
    expect(svg.attributes('viewBox')).toBe('0 0 16 16')
    expect(svg.attributes('width')).toBe('1em')
    expect(svg.attributes('height')).toBe('1em')
    expect(svg.attributes('fill')).toBe('currentColor')
    // shield-check 由两条 path 组成(轮廓 + 对勾)。
    expect(wrapper.findAll('path').length).toBe(2)
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('收录的每颗图标都渲染非空 path', () => {
    for (const name of ['box-arrow-up-right', 'shield-check', 'exclamation-triangle-fill']) {
      const wrapper = mount(Icon, { props: { name } })
      const paths = wrapper.findAll('path')
      expect(paths.length, name).toBeGreaterThan(0)
      for (const p of paths) expect(p.attributes('d'), name).toBeTruthy()
    }
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('未知 name:console.warn + 渲染为空,不抛错', () => {
    const wrapper = mount(Icon, { props: { name: 'no-such-icon' } })
    expect(wrapper.find('svg').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('<path')
    expect(warnSpy).toHaveBeenCalledTimes(1)
    expect(String(warnSpy.mock.calls[0][0])).toContain('no-such-icon')
  })

  it('默认是装饰性图标:aria-hidden="true"、无 role、无 aria-label', () => {
    const svg = mount(Icon, { props: { name: 'box-arrow-up-right' } }).find('svg')
    expect(svg.attributes('aria-hidden')).toBe('true')
    expect(svg.attributes('role')).toBeUndefined()
    expect(svg.attributes('aria-label')).toBeUndefined()
  })

  it('传 label 变语义图标:role="img" + aria-label,且不 aria-hidden', () => {
    const svg = mount(Icon, {
      props: { name: 'exclamation-triangle-fill', label: '警告' },
    }).find('svg')
    expect(svg.attributes('role')).toBe('img')
    expect(svg.attributes('aria-label')).toBe('警告')
    expect(svg.attributes('aria-hidden')).toBeUndefined()
  })

  it('class 透传到 svg 根节点(替换 <i class="bi bi-*"> 时保留布局 class)', () => {
    const svg = mount(Icon, {
      props: { name: 'box-arrow-up-right' },
      attrs: { class: 'ext-icon me-1' },
    }).find('svg')
    expect(svg.classes()).toContain('ext-icon')
    expect(svg.classes()).toContain('me-1')
    expect(svg.classes()).toContain('app-icon')
  })
})
