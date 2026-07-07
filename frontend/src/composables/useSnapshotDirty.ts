// Plan 2026-07-06-005 W2 — generic "is this local edit-surface state dirty
// relative to its last known-clean snapshot" tracker, used by every
// Settings card that hydrates a plain reactive form wholesale from a query
// (SettingsPage's keyword pools + schedule forms, BlogIdsCard, BloggerCard,
// LlmSettingsCard, NotionCard). ChannelBindingCard is the one card that
// doesn't use this — it already merges server data field-by-field without
// clobbering typed values, so it computes its own narrower dirty signal
// (see its own comment for why) but still registers with the same store.
//
// This ALSO fixes the hydration-overwrite bug (the reason W2 exists): each
// card's `watch(query.data, ...)` hydration callback is expected to check
// `dirty.value` and bail out before overwriting local state whenever the
// user has unsaved edits, then call `markClean()` once it does hydrate so
// the next edit is measured against the freshly-hydrated baseline.
import { onUnmounted, ref, watch, type WatchSource } from 'vue'
import { useSettingsDirtyStore } from '../stores/settingsDirty'

export interface SnapshotDirty {
  /** True when `source()` differs from the last `markClean()` baseline. */
  dirty: import('vue').Ref<boolean>
  /** Re-baseline against the current value of `source()` (call right after
   *  a successful hydration or a successful save). */
  markClean: () => void
}

/**
 * @param cardId stable id registered with the shared settings-dirty store.
 * @param label human-readable Chinese name shown in the route-leave warning.
 * @param source getter returning a JSON-serializable snapshot of the card's
 *   local editable state (e.g. `() => form` or `() => keywordEdits`).
 */
export function useSnapshotDirty(
  cardId: string,
  label: string,
  source: WatchSource<unknown>,
): SnapshotDirty {
  let baseline = JSON.stringify(typeof source === 'function' ? source() : source.value)
  const dirty = ref(false)

  watch(
    source,
    (val) => {
      dirty.value = JSON.stringify(val) !== baseline
    },
    { deep: true },
  )

  const store = useSettingsDirtyStore()
  watch(
    dirty,
    (v) => {
      if (v) store.setDirty(cardId, label)
      else store.clearDirty(cardId)
    },
    { immediate: true },
  )

  function markClean(): void {
    baseline = JSON.stringify(typeof source === 'function' ? source() : source.value)
    dirty.value = false
  }

  onUnmounted(() => store.clearDirty(cardId))

  return { dirty, markClean }
}
