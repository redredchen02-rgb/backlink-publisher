import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ArticleReviewRow from './ArticleReviewRow.vue'

const ROW = {
  id: 'r1',
  title: 'Original Title',
  custom_title: 'Custom Title',
  content_markdown: 'Original body text.',
  target_url: 'https://example.com/',
  anchors: 'anchor one\nanchor two',
}

function mountRow(props: { row?: object; patch?: object } = {}) {
  return mount(ArticleReviewRow, {
    props: {
      row: props.row ?? ROW,
      patch: props.patch ?? {},
    },
    attachTo: document.body,
  })
}

describe('ArticleReviewRow', () => {
  it('renders custom_title in the title input when no patch set', () => {
    const w = mountRow()
    const input = w.find('input[type="text"]')
    expect((input.element as HTMLInputElement).value).toBe('Custom Title')
  })

  it('uses patch.custom_title when provided', () => {
    const w = mountRow({ patch: { custom_title: 'Patched Title' } })
    const input = w.find('input[type="text"]')
    expect((input.element as HTMLInputElement).value).toBe('Patched Title')
  })

  it('emits patch event with new title on title input blur', async () => {
    const w = mountRow()
    const input = w.find('input[type="text"]')
    await input.setValue('New Title')
    await input.trigger('blur')
    const emitted = w.emitted('patch') as [object[]]
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toMatchObject({ custom_title: 'New Title' })
  })

  it('emits patch event with body on textarea blur', async () => {
    const w = mountRow()
    const textarea = w.find('textarea')
    await textarea.setValue('New body')
    await textarea.trigger('blur')
    const emitted = w.emitted('patch') as [object[]]
    expect(emitted).toBeTruthy()
    expect(emitted[0][0]).toMatchObject({ content_markdown: 'New body' })
  })

  it('shows empty textarea when content_markdown field is absent', () => {
    const row = { id: 'r2', title: 'T' }
    const w = mountRow({ row })
    const textarea = w.find('textarea')
    expect((textarea.element as HTMLTextAreaElement).value).toBe('')
  })

  it('shows edit indicator (*) when localTitle differs from originalTitle', async () => {
    const w = mountRow()
    const input = w.find('input[type="text"]')
    await input.setValue('Changed')
    expect(w.find('.review-row__edited').exists()).toBe(true)
  })

  it('does not show edit indicator when title unchanged', () => {
    const w = mountRow()
    expect(w.find('.review-row__edited').exists()).toBe(false)
  })

  it('syncs local state when patch prop changes', async () => {
    const w = mountRow({ patch: {} })
    await w.setProps({ patch: { custom_title: 'From Parent' } })
    const input = w.find('input[type="text"]')
    expect((input.element as HTMLInputElement).value).toBe('From Parent')
  })

  it('renders target_url as read-only text', () => {
    const w = mountRow()
    expect(w.text()).toContain('https://example.com/')
  })

  it('renders anchors as list items', () => {
    const w = mountRow()
    const items = w.findAll('.review-row__anchors li')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toBe('anchor one')
    expect(items[1].text()).toBe('anchor two')
  })

  it('hides anchors section when anchors field is absent', () => {
    const row = { id: 'r3', title: 'T' }
    const w = mountRow({ row })
    expect(w.find('.review-row__anchors').exists()).toBe(false)
  })
})
