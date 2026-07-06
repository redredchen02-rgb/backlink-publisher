import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from './DataTable.vue'

const ROWS = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

function mountTable(props: Record<string, unknown> = {}, slots: Record<string, string> = {}) {
  return mount(DataTable, {
    props: { items: ROWS, selected: new Set<string>(), ...props },
    slots: {
      head: '<th>Name</th>',
      row: '<td>{{ params.row.id }}</td>',
      ...slots,
    },
  })
}

describe('DataTable states', () => {
  it('loading -> StateBlock loading treatment, no table rows', () => {
    const w = mountTable({ loading: true })
    expect(w.find('[aria-busy="true"]').exists()).toBe(true)
    expect(w.findAll('tbody tr')).toHaveLength(0)
  })

  it('empty items -> StateBlock empty treatment, not a bare empty table', () => {
    const w = mountTable({ items: [], emptyText: '暂无数据自定义' })
    expect(w.text()).toContain('暂无数据自定义')
    expect(w.find('table').exists()).toBe(false)
  })

  it('error -> StateBlock error treatment', () => {
    const w = mountTable({ error: { status: 500 } })
    expect(w.find('[role="alert"]').exists()).toBe(true)
  })

  it('ready -> renders one row per item via the row slot', () => {
    const w = mountTable()
    expect(w.findAll('tbody tr')).toHaveLength(3)
    expect(w.text()).toContain('a')
    expect(w.text()).toContain('b')
    expect(w.text()).toContain('c')
  })
})

describe('DataTable row selection', () => {
  it('toggling a row checkbox emits update:selected with that id added', async () => {
    const w = mountTable({ selected: new Set<string>() })
    await w.find('tbody tr[data-id="a"] input[type="checkbox"]').setValue(true)
    const emitted = w.emitted('update:selected') as Array<[Set<string>]>
    expect(emitted[0][0]).toEqual(new Set(['a']))
  })

  it('toggling an already-selected row checkbox emits it removed', async () => {
    const w = mountTable({ selected: new Set(['a', 'b']) })
    await w.find('tbody tr[data-id="a"] input[type="checkbox"]').setValue(false)
    const emitted = w.emitted('update:selected') as Array<[Set<string>]>
    expect(emitted[0][0]).toEqual(new Set(['b']))
  })

  it('select-all header checkbox selects every visible row', async () => {
    const w = mountTable({ selected: new Set<string>() })
    await w.find('thead input[type="checkbox"]').setValue(true)
    const emitted = w.emitted('update:selected') as Array<[Set<string>]>
    expect(emitted[0][0]).toEqual(new Set(['a', 'b', 'c']))
  })

  it('select-all header checkbox clears selection when all already selected', async () => {
    const w = mountTable({ selected: new Set(['a', 'b', 'c']) })
    expect((w.find('thead input[type="checkbox"]').element as HTMLInputElement).checked).toBe(true)
    await w.find('thead input[type="checkbox"]').setValue(false)
    const emitted = w.emitted('update:selected') as Array<[Set<string>]>
    expect(emitted[0][0]).toEqual(new Set())
  })

  it('select-all checkbox is unchecked when only some rows are selected', () => {
    const w = mountTable({ selected: new Set(['a']) })
    expect((w.find('thead input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
  })
})

describe('DataTable pagination (opt-in)', () => {
  it('no pager rendered when limit/total are absent', () => {
    const w = mountTable()
    expect(w.find('.data-table__pager').exists()).toBe(false)
  })

  it('renders page/total text when limit+total are given', () => {
    const w = mountTable({ limit: 50, offset: 50, total: 120 })
    expect(w.text()).toContain('第 2 / 3 页')
    expect(w.text()).toContain('共 120 条')
  })

  it('prev button disabled on the first page', () => {
    const w = mountTable({ limit: 50, offset: 0, total: 120 })
    const [prev] = w.findAll('.data-table__pager button')
    expect((prev.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('next button disabled on the last page', () => {
    const w = mountTable({ limit: 50, offset: 100, total: 120 })
    const [, next] = w.findAll('.data-table__pager button')
    expect((next.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('clicking next emits the new offset AND clears the selection', async () => {
    const w = mountTable({ limit: 50, offset: 0, total: 120, selected: new Set(['a']) })
    const [, next] = w.findAll('.data-table__pager button')
    await next.trigger('click')
    expect(w.emitted('update:offset')![0]).toEqual([50])
    expect(w.emitted('update:selected')![0]).toEqual([new Set()])
  })

  it('clicking prev emits the previous offset AND clears the selection', async () => {
    const w = mountTable({ limit: 50, offset: 50, total: 120, selected: new Set(['b']) })
    const [prev] = w.findAll('.data-table__pager button')
    await prev.trigger('click')
    expect(w.emitted('update:offset')![0]).toEqual([0])
    expect(w.emitted('update:selected')![0]).toEqual([new Set()])
  })
})

describe('DataTable disabled (code review: pagination-during-mutation race)', () => {
  it('disables the pager buttons even when they would otherwise be enabled', () => {
    const w = mountTable({ limit: 50, offset: 50, total: 120, disabled: true })
    const [prev, next] = w.findAll('.data-table__pager button')
    expect((prev.element as HTMLButtonElement).disabled).toBe(true)
    expect((next.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('disables the select-all and per-row checkboxes', () => {
    const w = mountTable({ disabled: true })
    expect((w.find('thead input[type="checkbox"]').element as HTMLInputElement).disabled).toBe(true)
    expect(
      (w.find('tbody tr input[type="checkbox"]').element as HTMLInputElement).disabled,
    ).toBe(true)
  })

  it('a disabled pager button does not emit update:offset when clicked', async () => {
    const w = mountTable({ limit: 50, offset: 50, total: 120, disabled: true })
    const [, next] = w.findAll('.data-table__pager button')
    await next.trigger('click')
    expect(w.emitted('update:offset')).toBeUndefined()
  })
})
