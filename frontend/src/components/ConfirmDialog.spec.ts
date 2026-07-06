// ConfirmDialog — Plan 2026-07-06-005 W3 (R3) coverage.
//
// Covers the W3 acceptance scenarios:
//  - focus enters on open, Escape closes (emits cancel), focus returns to the
//    pre-open trigger element
//  - async confirm: button busy while pending; 5 rapid clicks → exactly 1 call
//  - confirm rejection: dialog stays open, inline error shown, button re-enabled
//  - danger variant class; role="dialog" + aria-modal + aria-labelledby wiring
//  - Escape dispatch: the dialog's capture-phase handler stops propagation so a
//    coexisting drawer (document bubble listener) does not also close
import { describe, expect, it } from 'vitest'
import { defineComponent, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import ConfirmDialog from './ConfirmDialog.vue'

/** Harness owning the controlled `open` state plus a focusable trigger. */
function makeHarness(opts: {
  danger?: boolean
  confirm?: () => unknown | Promise<unknown>
  confirmLabel?: string
} = {}) {
  const Harness = defineComponent({
    components: { ConfirmDialog },
    setup() {
      const open = ref(false)
      const cancelled = ref(0)
      const confirmedEvents = ref(0)
      return {
        open,
        cancelled,
        confirmedEvents,
        danger: opts.danger ?? false,
        confirmFn: opts.confirm,
        confirmLabel: opts.confirmLabel ?? '确认',
      }
    },
    template: `
      <div>
        <button class="trigger" type="button" @click="open = true">打开</button>
        <ConfirmDialog
          v-model:open="open"
          title="确认操作"
          :danger="danger"
          :confirm="confirmFn"
          :confirm-label="confirmLabel"
          @cancel="cancelled++"
          @confirm="confirmedEvents++"
        >
          <p>此操作不可撤销。</p>
        </ConfirmDialog>
      </div>
    `,
  })
  // attachTo: focus assertions need the elements in the real document.
  return mount(Harness, { attachTo: document.body })
}

function pressEscape(target: Element) {
  target.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }),
  )
}

describe('ConfirmDialog — a11y contract', () => {
  it('renders role="dialog" + aria-modal + aria-labelledby pointing at the title, and an aria-live body', async () => {
    const w = makeHarness()
    await w.find('.trigger').trigger('click')

    const dialog = w.find('[role="dialog"]')
    expect(dialog.exists()).toBe(true)
    expect(dialog.attributes('aria-modal')).toBe('true')
    const labelledby = dialog.attributes('aria-labelledby')
    expect(labelledby).toBeTruthy()
    const title = w.find(`#${labelledby}`)
    expect(title.exists()).toBe(true)
    expect(title.text()).toBe('确认操作')
    expect(w.find('.cdlg__body').attributes('aria-live')).toBe('polite')
    w.unmount()
  })

  it('applies the danger variant class to the confirm button and modal', async () => {
    const w = makeHarness({ danger: true })
    await w.find('.trigger').trigger('click')
    expect(w.find('.cdlg__confirm--danger').exists()).toBe(true)
    expect(w.find('.cdlg__confirm--primary').exists()).toBe(false)
    expect(w.find('.cdlg__modal--danger').exists()).toBe(true)
    w.unmount()
  })

  it('non-danger default uses the primary confirm variant', async () => {
    const w = makeHarness()
    await w.find('.trigger').trigger('click')
    expect(w.find('.cdlg__confirm--primary').exists()).toBe(true)
    expect(w.find('.cdlg__confirm--danger').exists()).toBe(false)
    w.unmount()
  })
})

describe('ConfirmDialog — focus + Escape lifecycle', () => {
  it('open → focus enters the dialog; Escape → closes, emits cancel, focus returns to trigger', async () => {
    const w = makeHarness()
    const trigger = w.find('.trigger').element as HTMLButtonElement
    trigger.focus()
    await w.find('.trigger').trigger('click')
    await nextTick()

    // Focus moved into the dialog (first focusable = confirm button)
    const confirmBtn = w.find('.cdlg__confirm').element as HTMLElement
    expect(document.activeElement).toBe(confirmBtn)

    pressEscape(confirmBtn)
    await nextTick()

    expect(w.find('[role="dialog"]').exists()).toBe(false)
    expect((w.vm as unknown as { cancelled: number }).cancelled).toBe(1)
    expect(document.activeElement).toBe(trigger)
    w.unmount()
  })

  it('cancel button closes, emits cancel and restores focus to the trigger', async () => {
    const w = makeHarness()
    const trigger = w.find('.trigger').element as HTMLButtonElement
    trigger.focus()
    await w.find('.trigger').trigger('click')
    await nextTick()

    await w.find('.cdlg__cancel').trigger('click')
    expect(w.find('[role="dialog"]').exists()).toBe(false)
    expect((w.vm as unknown as { cancelled: number }).cancelled).toBe(1)
    expect(document.activeElement).toBe(trigger)
    w.unmount()
  })

  it('Escape is handled in capture phase with stopPropagation — a coexisting drawer bubble listener never sees it', async () => {
    const drawerSaw: string[] = []
    const drawerListener = (e: KeyboardEvent) => {
      if (e.key === 'Escape') drawerSaw.push('escape')
    }
    // Simulates useSidenavDrawer: bubble-phase keydown listener on document.
    document.addEventListener('keydown', drawerListener)
    try {
      const w = makeHarness()
      await w.find('.trigger').trigger('click')
      await nextTick()

      pressEscape(w.find('.cdlg__confirm').element)
      await nextTick()

      expect(w.find('[role="dialog"]').exists()).toBe(false) // dialog closed
      expect(drawerSaw).toEqual([]) // drawer untouched — topmost layer closes first
      w.unmount()

      // With the dialog gone, the drawer receives Escape again.
      pressEscape(document.body)
      expect(drawerSaw).toEqual(['escape'])
    } finally {
      document.removeEventListener('keydown', drawerListener)
    }
  })

  it('restores the previous body overflow on close (does not unlock an outer scroll lock)', async () => {
    document.body.style.overflow = 'hidden' // e.g. drawer already open
    const w = makeHarness()
    await w.find('.trigger').trigger('click')
    expect(document.body.style.overflow).toBe('hidden')
    await w.find('.cdlg__cancel').trigger('click')
    expect(document.body.style.overflow).toBe('hidden') // drawer's lock survives
    w.unmount()
    document.body.style.overflow = ''
  })
})

describe('ConfirmDialog — async confirm', () => {
  it('confirm button is busy while pending; 5 rapid clicks trigger exactly 1 callback', async () => {
    let calls = 0
    let release!: () => void
    const confirm = () => {
      calls++
      return new Promise<void>((resolve) => { release = resolve })
    }
    const w = makeHarness({ confirm, confirmLabel: '确认删除（3 条）' })
    await w.find('.trigger').trigger('click')

    const btn = w.find('.cdlg__confirm')
    expect(btn.text()).toBe('确认删除（3 条）')

    for (let i = 0; i < 5; i++) await btn.trigger('click')

    expect(calls).toBe(1)
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('aria-busy')).toBe('true')
    expect(btn.text()).toBe('处理中…')
    // Cancel is also locked while in flight
    expect(w.find('.cdlg__cancel').attributes('disabled')).toBeDefined()
    // Escape is ignored while busy
    pressEscape(btn.element)
    await nextTick()
    expect(w.find('[role="dialog"]').exists()).toBe(true)

    release()
    await flushPromises()
    expect(w.find('[role="dialog"]').exists()).toBe(false) // resolve → auto close
    w.unmount()
  })

  it('rejection keeps the dialog open, shows an inline error and re-enables the button', async () => {
    let attempts = 0
    const confirm = () => {
      attempts++
      return Promise.reject(new Error('服务器错误 500'))
    }
    const w = makeHarness({ confirm })
    await w.find('.trigger').trigger('click')

    await w.find('.cdlg__confirm').trigger('click')
    await flushPromises()

    // Not silently closed
    expect(w.find('[role="dialog"]').exists()).toBe(true)
    const err = w.find('.cdlg__error')
    expect(err.exists()).toBe(true)
    expect(err.attributes('role')).toBe('alert')
    expect(err.text()).toContain('服务器错误 500')
    // Button restored — retry is possible
    const btn = w.find('.cdlg__confirm')
    expect(btn.attributes('disabled')).toBeUndefined()
    await btn.trigger('click')
    await flushPromises()
    expect(attempts).toBe(2)
    w.unmount()
  })

  it('a previous inline error is cleared when the dialog is reopened', async () => {
    const confirm = () => Promise.reject(new Error('boom'))
    const w = makeHarness({ confirm })
    await w.find('.trigger').trigger('click')
    await w.find('.cdlg__confirm').trigger('click')
    await flushPromises()
    expect(w.find('.cdlg__error').exists()).toBe(true)

    await w.find('.cdlg__cancel').trigger('click')
    await w.find('.trigger').trigger('click')
    expect(w.find('.cdlg__error').exists()).toBe(false)
    w.unmount()
  })

  it('without a confirm prop, clicking confirm emits the confirm event and leaves open-state to the parent', async () => {
    const w = makeHarness()
    await w.find('.trigger').trigger('click')
    await w.find('.cdlg__confirm').trigger('click')
    const vm = w.vm as unknown as { confirmedEvents: number }
    expect(vm.confirmedEvents).toBe(1)
    // Controlled mode: dialog stays open until the parent flips `open`.
    expect(w.find('[role="dialog"]').exists()).toBe(true)
    w.unmount()
  })
})

describe('ConfirmDialog — focus trap', () => {
  it('Tab from the last focusable wraps to the first (and Shift+Tab wraps back)', async () => {
    const w = makeHarness()
    await w.find('.trigger').trigger('click')
    await nextTick()

    const confirmBtn = w.find('.cdlg__confirm').element as HTMLElement
    const cancelBtn = w.find('.cdlg__cancel').element as HTMLElement

    cancelBtn.focus()
    cancelBtn.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }),
    )
    expect(document.activeElement).toBe(confirmBtn)

    confirmBtn.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }),
    )
    expect(document.activeElement).toBe(cancelBtn)
    w.unmount()
  })
})
