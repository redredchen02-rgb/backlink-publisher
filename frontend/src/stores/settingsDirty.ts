// Plan 2026-07-06-005 W2 — shared "unsaved Settings edits" registry.
//
// Settings is 10 independently-saveable sections (Files list: SettingsPage's
// own 2 forms — keyword pools + publish cadence — plus BlogIdsCard,
// BloggerCard, ChannelBindingCard, LlmSettingsCard, NotionCard). Each section
// registers its own dirty/clean state here under a stable card id; consumers
// (the router's route-leave guard, the `beforeunload` handler in
// `router/index.ts`) only need `anyDirty` / `dirtyLabels` and never need to
// know which cards exist. This is the single source of truth both the guard
// and every card read/write — keeping it here (not duplicated per card) is
// what makes "card A dirty, card B saved → warning only mentions A" possible.
import { defineStore } from 'pinia'
import { computed, reactive } from 'vue'

export const useSettingsDirtyStore = defineStore('settings-dirty', () => {
  // cardId -> human-readable label (Chinese section name), present only
  // while that card has unsaved edits. A plain reactive object (not a Map)
  // so Pinia's devtools/serialization and `deep` watches work without extra
  // plumbing — the keyspace is tiny (≤10 entries) so this is not a
  // performance concern.
  const dirty = reactive<Record<string, string>>({})

  function setDirty(cardId: string, label: string): void {
    dirty[cardId] = label
  }

  function clearDirty(cardId: string): void {
    delete dirty[cardId]
  }

  /** Called after the user confirms "leave anyway" in the route-leave guard. */
  function clearAll(): void {
    for (const key of Object.keys(dirty)) delete dirty[key]
  }

  const anyDirty = computed(() => Object.keys(dirty).length > 0)
  const dirtyLabels = computed(() => Object.values(dirty))

  return { dirty, setDirty, clearDirty, clearAll, anyDirty, dirtyLabels }
})
