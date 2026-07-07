// Plan 2026-07-06-005 W6 — shared Settings save convention: 422 inline
// validation (no global toast), success toast, per-card save-in-flight busy,
// and a hook into W2's `useSnapshotDirty` (`markClean`). Wraps the repeated
// try/saving/catch(ApiError 422)/finally block that used to be duplicated
// across every Settings*Card.vue into one `run()` call.
//
// Field-level mapping caveat: the backend returns a single freeform `detail`
// string (problem+json), not a structured {field, message} list, and W6's
// scope explicitly excludes touching backend write paths (they already go
// through `save_config` governance — see the plan's W6 section). So "field
// level" here is a best-effort regex match against an optional `fieldMap`
// (field name -> pattern expected to appear in the detail string, tried in
// declaration order, first match wins). A detail that matches no pattern —
// or a caller that passes no `fieldMap` at all — still renders inline as
// `formError` rather than a toast; it just isn't attributed to one specific
// input. Either way the invariant holds for every caller: a 422 NEVER
// produces a global error toast, only inline text the card renders itself.
// Plan 2026-07-06-005 W13 (D7/D8): this composable is already the shape W13
// wants (per-card busy + toast + dirty integration) — it is NOT migrated to
// `useMutation` (that would mean rewriting its 422-vs-toast branching, out of
// this unit's scope). Its non-422 catch branch (below) is instead wired to
// `reportManualMutationError`, the same manual-reporting helper HistoryPage
// uses, so a save failure reaches error-reports exactly like a real
// MutationCache-observed mutation would. The 422 branch never calls it — a
// 422 here is expected inline-validation, not an incident (D8).
import { reactive, ref, type Ref } from 'vue'
import { ApiError } from '../api/client'
import { useErrorToast } from './useErrorToast'
import { reportManualMutationError } from '../lib/errorCapture'
import { useNotificationsStore } from '../stores/notifications'

/** field name -> pattern tested against the 422 `detail` string. */
export type SettingsFormFieldMap = Record<string, RegExp>

export interface SettingsFormRunOptions<T> {
  /** Fallback toast text if the response has no `message`. */
  successMessage?: string
  /** Called with the successful response, before `markClean()` re-baselines. */
  onSuccess?: (result: T) => void
}

export interface SettingsForm {
  /** True while a save is in flight. Bind to `:disabled` on THIS card's submit button only —
   *  every card gets its own instance, so one card saving never disables another. */
  saving: Ref<boolean>
  /** Non-field-attributable 422 detail (or a fieldMap miss) — render inline near the submit button. */
  formError: Ref<string | null>
  /** field name -> 422 detail attributed to it via `fieldMap` — render inline under that input. */
  fieldErrors: Record<string, string>
  /** Reset both error surfaces. Called automatically at the start of every `run()`. */
  clearErrors: () => void
  /**
   * Run a save action.
   * - success → toast (`result.message` or `successMessage`), `onSuccess(result)`, `markClean()`.
   * - 422 → attribute `detail` to `fieldErrors[field]` on the first `fieldMap` match, else
   *   `formError`. Never toasts.
   * - any other error → routed through `toastError` (classifyError-driven sticky toast), same
   *   as before W6.
   * No-ops (returns `undefined` without touching state) if a save is already in flight.
   */
  run: <T extends { message?: string }>(
    action: () => Promise<T>,
    options?: SettingsFormRunOptions<T>,
  ) => Promise<T | undefined>
}

function detailOf(payload: unknown): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const d = (payload as Record<string, unknown>).detail
    if (d != null) return String(d)
  }
  return '校验失败'
}

/**
 * @param markClean called after a successful save — pass the `markClean` returned by this
 *   card's `useSnapshotDirty` (W2) so a save re-baselines dirty tracking exactly like before.
 * @param fieldMap optional field name -> RegExp tested against the 422 `detail`, in declaration
 *   order — attributes the error to one input's `fieldErrors[name]` instead of the shared
 *   `formError` banner.
 * @param context optional free-form label (never raw call arguments) identifying which card's
 *   save this is, e.g. `'settings.llm'` — forwarded to `reportManualMutationError` (W13) so a
 *   non-422 failure's error-report is traceable back to its card. Defaults to `'settings.save'`
 *   for existing call sites that don't pass one.
 */
export function useSettingsForm(
  markClean: () => void,
  fieldMap: SettingsFormFieldMap = {},
  context = 'settings.save',
): SettingsForm {
  const notify = useNotificationsStore()
  const { toastError } = useErrorToast()
  const saving = ref(false)
  const formError = ref<string | null>(null)
  const fieldErrors = reactive<Record<string, string>>({})

  function clearErrors(): void {
    formError.value = null
    for (const k of Object.keys(fieldErrors)) delete fieldErrors[k]
  }

  async function run<T extends { message?: string }>(
    action: () => Promise<T>,
    options: SettingsFormRunOptions<T> = {},
  ): Promise<T | undefined> {
    if (saving.value) return undefined
    saving.value = true
    clearErrors()
    try {
      const result = await action()
      notify.push(result.message || options.successMessage || '已保存', 'success')
      options.onSuccess?.(result)
      markClean()
      return result
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        const detail = detailOf(e.payload)
        const field = Object.entries(fieldMap).find(([, pattern]) => pattern.test(detail))?.[0]
        if (field) fieldErrors[field] = detail
        else formError.value = detail
        return undefined
      }
      // D8: non-422 is an incident-class signal (CSRF 403, invariant-violation
      // 400, 5xx, network) — report it, same as a real MutationCache-observed
      // mutation would, in addition to the existing toast.
      reportManualMutationError(e, context)
      toastError(e)
      return undefined
    } finally {
      saving.value = false
    }
  }

  return { saving, formError, fieldErrors, clearErrors, run }
}
