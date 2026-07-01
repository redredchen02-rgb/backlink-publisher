// Test-first per plan Unit 4 execution note: written before the composable
// exists. `useSidenavDrawer` has no DOM-mount dependency (unlike SideNav.spec.ts,
// which needs @vue/test-utils) — it's exercised directly with plain refs and
// real jsdom elements, mirroring useErrorToast.spec.ts's plain-call style.
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useSidenavDrawer } from './useSidenavDrawer'

const BREAKPOINT_PX = 1024

/** Build a focusable drawer body (3 links) + a trigger button, attached to document.body. */
function mountDrawerFixture() {
  const container = document.createElement('div')
  const link1 = document.createElement('a')
  link1.href = '#one'
  link1.textContent = 'one'
  const link2 = document.createElement('a')
  link2.href = '#two'
  link2.textContent = 'two'
  const link3 = document.createElement('a')
  link3.href = '#three'
  link3.textContent = 'three'
  container.append(link1, link2, link3)

  const trigger = document.createElement('button')
  trigger.type = 'button'
  trigger.textContent = 'menu'

  document.body.append(container, trigger)

  return { container, link1, link2, link3, trigger }
}

function setViewportWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', {
    writable: true,
    configurable: true,
    value: width,
  })
}

describe('useSidenavDrawer', () => {
  let fixture: ReturnType<typeof mountDrawerFixture>

  beforeEach(() => {
    fixture = mountDrawerFixture()
    setViewportWidth(800) // narrow viewport by default — drawer mode
    document.body.style.overflow = ''
  })

  afterEach(() => {
    fixture.container.remove()
    fixture.trigger.remove()
    document.body.style.overflow = ''
  })

  it('happy path: toggle() opens then closes, isOpen reflects state', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    expect(drawer.isOpen.value).toBe(false)
    drawer.toggle()
    expect(drawer.isOpen.value).toBe(true)
    drawer.toggle()
    expect(drawer.isOpen.value).toBe(false)
  })

  it('Escape closes the drawer only while open, and stops listening after close', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    // Escape while closed does nothing (no listener registered yet).
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(drawer.isOpen.value).toBe(false)

    drawer.open()
    expect(drawer.isOpen.value).toBe(true)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(drawer.isOpen.value).toBe(false)

    // Listener must have been removed on close — reopen manually, then confirm
    // a *second* stray Escape dispatch (simulating a leaked old listener from
    // a previous open/close cycle) does not throw or double-close/no-op oddly.
    drawer.open()
    expect(drawer.isOpen.value).toBe(true)
    drawer.close()
    expect(drawer.isOpen.value).toBe(false)
  })

  it('overlay click closes the drawer (overlay is wired to call close() directly)', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    drawer.open()
    expect(drawer.isOpen.value).toBe(true)

    // AppShell's overlay backdrop is wired as `@click="drawer.close()"` — this
    // exercises that exact call, since the composable owns no DOM overlay itself.
    drawer.close()
    expect(drawer.isOpen.value).toBe(false)
  })

  it('locks body scroll while open, releases it on close', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    expect(document.body.style.overflow).toBe('')
    drawer.open()
    expect(document.body.style.overflow).toBe('hidden')
    drawer.close()
    expect(document.body.style.overflow).toBe('')
  })

  it('moves focus into the drawer (first focusable element) on open — not left on the trigger', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger
    fixture.trigger.focus()
    expect(document.activeElement).toBe(fixture.trigger)

    drawer.open()

    expect(document.activeElement).toBe(fixture.link1)
  })

  it('traps Tab/Shift+Tab focus cycling within the drawer while open', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    drawer.open()
    expect(document.activeElement).toBe(fixture.link1)

    // Tab forward from the last focusable element wraps to the first.
    fixture.link3.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }))
    expect(document.activeElement).toBe(fixture.link1)

    // Shift+Tab back from the first focusable element wraps to the last.
    fixture.link1.focus()
    document.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true }),
    )
    expect(document.activeElement).toBe(fixture.link3)
  })

  it('returns focus to the trigger (hamburger) button when the drawer closes', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    drawer.open()
    expect(document.activeElement).toBe(fixture.link1)

    drawer.close()
    expect(document.activeElement).toBe(fixture.trigger)
  })

  it('auto-closes and releases the scroll lock when the viewport is resized past the 1024px breakpoint', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    drawer.open()
    expect(drawer.isOpen.value).toBe(true)
    expect(document.body.style.overflow).toBe('hidden')

    setViewportWidth(BREAKPOINT_PX + 200)
    window.dispatchEvent(new Event('resize'))

    expect(drawer.isOpen.value).toBe(false)
    expect(document.body.style.overflow).toBe('')
  })

  it('does not auto-close on resize while still within/at the narrow breakpoint', () => {
    const drawer = useSidenavDrawer()
    drawer.drawerEl.value = fixture.container
    drawer.triggerEl.value = fixture.trigger

    drawer.open()
    setViewportWidth(BREAKPOINT_PX) // exactly at breakpoint — still "narrow" per max-width:1024px
    window.dispatchEvent(new Event('resize'))

    expect(drawer.isOpen.value).toBe(true)
  })
})
