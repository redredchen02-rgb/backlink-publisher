import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from '../components/DataTable.vue'

const items = [
  { id: 'a', name: '甲' },
  { id: 'b', name: '乙' },
]

function make(props: Record<string, unknown> = {}) {
  return mount(DataTable, {
    props: { items, ...props },
    slots: {
      head: '<th>名称</th>',
      row: `<template #row="{ row }"><td>{{ row.name }}</td></template>`,
    },
  })
}

describe('DataTable selectable prop', () => {
  it('hides the select column by default', () => {
    const w = make()
    expect(w.find('.col-select').exists()).toBe(false)
  })

  it('renders the select column when selectable', () => {
    const w = make({ selectable: true })
    expect(w.findAll('th.col-select')).toHaveLength(1)
    expect(w.findAll('td.col-select')).toHaveLength(items.length)
  })
})

describe('DataTable click-to-activate', () => {
  it('emits rowActivate on row click when rowKeyboardNav', async () => {
    const w = make({ rowKeyboardNav: true })
    await w.findAll('tbody tr')[0].trigger('click')
    expect(w.emitted('rowActivate')?.[0]).toEqual([items[0]])
  })

  it('does not emit rowActivate without rowKeyboardNav', async () => {
    const w = make()
    await w.findAll('tbody tr')[0].trigger('click')
    expect(w.emitted('rowActivate')).toBeUndefined()
  })

  it('does not emit rowActivate for clicks on nested interactive controls', async () => {
    const w = mount(DataTable, {
      props: { items, rowKeyboardNav: true },
      slots: {
        head: '<th>操作</th>',
        row: `<template #row="{ row }"><td><button type="button">编辑</button></td></template>`,
      },
    })
    await w.find('tbody tr button').trigger('click')
    expect(w.emitted('rowActivate')).toBeUndefined()
  })
})
