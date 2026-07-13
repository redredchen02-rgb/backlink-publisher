import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from './DataTable.vue'

const ROWS = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

function mountTable(props: Record<string, unknown> = {}, slots: Record<string, string> = {}) {
  return mount(DataTable, {
    props: { items: ROWS, selected: new Set<string>(), selectable: true, ...props },
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

describe('DataTable a11y structure (W11)', () => {
  it('renders no <caption> when caption prop is the default empty string', () => {
    const w = mountTable()
    expect(w.find('caption').exists()).toBe(false)
  })

  it('renders a sr-only <caption> with the given text when caption is set', () => {
    const w = mountTable({ caption: '发布历史列表' })
    const caption = w.find('caption')
    expect(caption.exists()).toBe(true)
    expect(caption.classes()).toContain('sr-only')
    expect(caption.text()).toBe('发布历史列表')
  })

  it('the select-all header cell carries scope="col"', () => {
    const w = mountTable()
    expect(w.find('thead th.col-select').attributes('scope')).toBe('col')
  })

  it('select-all checkbox: unchecked/not-indeterminate when nothing is selected', () => {
    const w = mountTable({ selected: new Set<string>() })
    const cb = w.find('thead input[type="checkbox"]').element as HTMLInputElement
    expect(cb.checked).toBe(false)
    expect(cb.indeterminate).toBe(false)
    expect(cb.getAttribute('aria-label')).toBe('全选本页')
  })

  it('select-all checkbox: indeterminate + "部分选中" aria-label when some (not all) rows selected', () => {
    const w = mountTable({ selected: new Set(['a']) })
    const cb = w.find('thead input[type="checkbox"]').element as HTMLInputElement
    expect(cb.checked).toBe(false)
    expect(cb.indeterminate).toBe(true)
    expect(cb.getAttribute('aria-label')).toBe('部分选中')
  })

  it('select-all checkbox: checked + not indeterminate + "取消全选" aria-label when every row selected', () => {
    const w = mountTable({ selected: new Set(['a', 'b', 'c']) })
    const cb = w.find('thead input[type="checkbox"]').element as HTMLInputElement
    expect(cb.checked).toBe(true)
    expect(cb.indeterminate).toBe(false)
    expect(cb.getAttribute('aria-label')).toBe('取消全选')
  })

  it('three-state cycle: none -> some -> all -> none via toggling rows/select-all', async () => {
    const w = mountTable({ selected: new Set<string>() })
    const cbOf = () => w.find('thead input[type="checkbox"]').element as HTMLInputElement
    expect(cbOf().indeterminate).toBe(false)

    await w.setProps({ selected: new Set(['a']) })
    expect(cbOf().indeterminate).toBe(true)

    await w.setProps({ selected: new Set(['a', 'b', 'c']) })
    expect(cbOf().indeterminate).toBe(false)
    expect(cbOf().checked).toBe(true)

    await w.setProps({ selected: new Set<string>() })
    expect(cbOf().indeterminate).toBe(false)
    expect(cbOf().checked).toBe(false)
  })
})

describe('DataTable keyboard row navigation (W11, rowKeyboardNav)', () => {
  it('rowKeyboardNav=false (default): rows carry no tabindex and arrows do nothing', async () => {
    const w = mountTable()
    const rows = w.findAll('tbody tr')
    for (const r of rows) {
      expect(r.attributes('tabindex')).toBeUndefined()
    }
    await rows[0].trigger('keydown', { key: 'ArrowDown' })
    // no crash, no rowActivate/focus side effects to observe beyond absence of tabindex
    expect(w.emitted('rowActivate')).toBeUndefined()
  })

  it('rowKeyboardNav=true: first row defaults to tabindex=0, others -1, before any interaction', () => {
    const w = mountTable({ rowKeyboardNav: true })
    const rows = w.findAll('tbody tr')
    expect(rows[0].attributes('tabindex')).toBe('0')
    expect(rows[1].attributes('tabindex')).toBe('-1')
    expect(rows[2].attributes('tabindex')).toBe('-1')
  })

  it('ArrowDown moves the roving tabindex to the next row and focuses it', async () => {
    const w = mountTable({ rowKeyboardNav: true })
    document.body.appendChild(w.element)
    const rows = w.findAll('tbody tr')
    await rows[0].trigger('keydown', { key: 'ArrowDown' })
    expect(w.findAll('tbody tr')[0].attributes('tabindex')).toBe('-1')
    expect(w.findAll('tbody tr')[1].attributes('tabindex')).toBe('0')
    w.element.remove()
  })

  it('ArrowDown at the last row stays clamped (no out-of-range focus)', async () => {
    const w = mountTable({ rowKeyboardNav: true })
    document.body.appendChild(w.element)
    const rows = w.findAll('tbody tr')
    await rows[2].trigger('keydown', { key: 'ArrowDown' })
    expect(w.findAll('tbody tr')[2].attributes('tabindex')).toBe('0')
    w.element.remove()
  })

  it('ArrowUp at the first row stays clamped', async () => {
    const w = mountTable({ rowKeyboardNav: true })
    const rows = w.findAll('tbody tr')
    await rows[0].trigger('keydown', { key: 'ArrowUp' })
    expect(w.findAll('tbody tr')[0].attributes('tabindex')).toBe('0')
  })

  it('Enter on a focused row emits rowActivate with that row', async () => {
    const w = mountTable({ rowKeyboardNav: true })
    const rows = w.findAll('tbody tr')
    await rows[1].trigger('keydown', { key: 'Enter' })
    expect(w.emitted('rowActivate')![0]).toEqual([{ id: 'b' }])
  })

  it('rowKeyboardNav=true but disabled=true: no tabindex, arrows/Enter are no-ops', async () => {
    const w = mountTable({ rowKeyboardNav: true, disabled: true })
    const rows = w.findAll('tbody tr')
    expect(rows[0].attributes('tabindex')).toBeUndefined()
    await rows[0].trigger('keydown', { key: 'Enter' })
    expect(w.emitted('rowActivate')).toBeUndefined()
  })

  it('a keydown bubbling from a nested control (not the <tr> itself) is ignored', async () => {
    const w = mountTable({ rowKeyboardNav: true })
    const checkbox = w.find('tbody tr[data-id="a"] input[type="checkbox"]')
    await checkbox.trigger('keydown', { key: 'Enter' })
    expect(w.emitted('rowActivate')).toBeUndefined()
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
