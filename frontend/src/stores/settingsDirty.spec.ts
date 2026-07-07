import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useSettingsDirtyStore } from './settingsDirty'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useSettingsDirtyStore', () => {
  it('starts clean', () => {
    const store = useSettingsDirtyStore()
    expect(store.anyDirty).toBe(false)
    expect(store.dirtyLabels).toEqual([])
  })

  it('setDirty/clearDirty toggle anyDirty and dirtyLabels per card id', () => {
    const store = useSettingsDirtyStore()
    store.setDirty('card-a', 'Card A')
    expect(store.anyDirty).toBe(true)
    expect(store.dirtyLabels).toEqual(['Card A'])

    store.setDirty('card-b', 'Card B')
    expect(store.dirtyLabels.slice().sort()).toEqual(['Card A', 'Card B'])

    store.clearDirty('card-a')
    expect(store.dirtyLabels).toEqual(['Card B'])
    expect(store.anyDirty).toBe(true)

    store.clearDirty('card-b')
    expect(store.anyDirty).toBe(false)
  })

  it('clearAll wipes every registered card', () => {
    const store = useSettingsDirtyStore()
    store.setDirty('card-a', 'Card A')
    store.setDirty('card-b', 'Card B')
    store.clearAll()
    expect(store.anyDirty).toBe(false)
    expect(store.dirtyLabels).toEqual([])
  })

  it('clearDirty on an id that was never dirty is a no-op', () => {
    const store = useSettingsDirtyStore()
    store.clearDirty('never-set')
    expect(store.anyDirty).toBe(false)
  })
})
