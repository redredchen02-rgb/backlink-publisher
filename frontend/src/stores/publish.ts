// Publish-workbench store — Plan 2026-06-18-002 U5.
//
// This Pinia store holds the four-stage state (input → planned → validated →
// published) CLIENT-SIDE. It is the SPA replacement for the legacy Flask
// `session` that threaded `plans`/`validated`/`config` across the /ce:* POSTs:
// the /api/v1/pipeline/* endpoints are stateless, so the workbench owns the
// stage state and passes it explicitly in each call.
//
// Actions are thin: they call the typed pipeline client and stash the rows.
// Errors propagate to the caller (the page surfaces them via classifyError +
// the notifications toast); the store only flips the per-action busy flags so
// the UI can disable controls (publish double-submit would race dedup.db).

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { createOperation, type OperationStatus } from '../api/operations'
import * as api from '../api/pipeline'

export type Stage = 'input' | 'planned' | 'validated' | 'published'

export type PlanRowPatch = {
  custom_title?: string
  content_markdown?: string
}

export interface PublishConfig {
  platform: string
  publishMode: string
  urlMode: string
  targetLanguage: string
  customTitle: string
  customTags: string
  fetchTdk: string
  tier1: boolean
}

function defaultConfig(): PublishConfig {
  return {
    platform: 'blogger',
    publishMode: 'publish',
    urlMode: 'C',
    targetLanguage: 'zh-CN',
    customTitle: '',
    customTags: '',
    fetchTdk: 'no',
    tier1: false,
  }
}

export const usePublishStore = defineStore('publish', () => {
  const urls = ref<string[]>([])
  const config = ref<PublishConfig>(defaultConfig())
  const plans = ref<api.PlanRow[]>([])
  const validated = ref<api.PlanRow[]>([])
  const edits = ref<Record<number, PlanRowPatch>>({})
  const publishResult = ref<api.PublishResult | null>(null)

  const availablePlatforms = ref<api.Platform[]>([])
  // Surfaced (but non-fatal) bootstrap failure — loadPlatforms() itself stays
  // tolerant (keeps the current default so the form works either way); this
  // just lets the page show a persistent, in-place indicator instead of the
  // failure being invisible (R3 action 6/7).
  const platformsError = ref<unknown>(null)

  const planning = ref(false)
  const validating = ref(false)
  const publishing = ref(false)
  // Active async publish operation (Plan 2026-07-09 operation-progress P2).
  // Set by runPublish() on the 202 response; the page renders
  // <OperationProgress> off it and calls settlePublish() on the terminal
  // status. `publishing` stays true for the whole run so the double-submit
  // guard and the soft-timeout watcher keep one source of truth.
  const publishOpId = ref<string | null>(null)

  const effectivePlans = computed<api.PlanRow[]>(() =>
    validated.value.map((row, i) =>
      edits.value[i] ? { ...row, ...edits.value[i] } : row,
    ),
  )

  function clearEdits(): void {
    edits.value = {}
  }

  function patchRow(idx: number, patch: PlanRowPatch): void {
    edits.value[idx] = { ...edits.value[idx], ...patch }
  }

  const stage = computed<Stage>(() => {
    if (publishResult.value) return 'published'
    if (validated.value.length) return 'validated'
    if (plans.value.length) return 'planned'
    return 'input'
  })

  const busy = computed(() => planning.value || validating.value || publishing.value)

  /** Load the bound-platform picker options; tolerant of failure (keeps the
   *  current default so the form still works if the bootstrap call fails). */
  async function loadPlatforms(): Promise<void> {
    try {
      availablePlatforms.value = (await api.boundPlatforms()).platforms
      platformsError.value = null
    } catch (e) {
      platformsError.value = e
      /* keep whatever we have; the platform field still defaults to 'blogger' */
    }
  }

  /** Parse a textarea of newline-separated URLs into the urls list. */
  function setUrls(raw: string): void {
    urls.value = raw
      .split('\n')
      .map((u) => u.trim())
      .filter(Boolean)
  }

  function planPayload(): api.PlanPayload {
    const c = config.value
    return {
      urls: urls.value,
      platform: c.platform,
      url_mode: c.urlMode,
      publish_mode: c.publishMode,
      target_language: c.targetLanguage,
      custom_title: c.customTitle,
      custom_tags: c.customTags,
      fetch_tdk: c.fetchTdk,
    }
  }

  async function runPlan(): Promise<void> {
    planning.value = true
    try {
      const r = await api.planBacklinks(planPayload())
      plans.value = r.plans
      // Re-planning invalidates downstream stages.
      validated.value = []
      clearEdits()
      publishResult.value = null
    } finally {
      planning.value = false
    }
  }

  async function runValidate(): Promise<void> {
    validating.value = true
    try {
      const r = await api.validateBacklinks(plans.value)
      validated.value = r.validated
      clearEdits()
      publishResult.value = null
    } finally {
      validating.value = false
    }
  }

  async function runPublish(): Promise<void> {
    // Hard guard against a double-submit racing the dedup.db single-flight
    // (the backend worker additionally enforces single-flight per kind).
    if (publishing.value) return
    publishing.value = true
    publishResult.value = null
    try {
      const c = config.value
      const { op_id } = await createOperation({
        kind: 'publish',
        plans: effectivePlans.value,
        platform: c.platform,
        publish_mode: c.publishMode,
        tier_1: c.tier1,
        target_language: c.targetLanguage,
        target_url: urls.value[0],
      })
      publishOpId.value = op_id
      // `publishing` intentionally NOT cleared here — the op runs in the
      // backend worker; settlePublish() clears it on the terminal status.
    } catch (e) {
      publishing.value = false
      throw e
    }
  }

  /** Terminal-status handler for the async publish op (called by the page's
   *  OperationProgress @settled). Maps the worker's result payload onto the
   *  legacy PublishResult shape (`n_total` = ok + failed) so the existing
   *  result panel renders unchanged. */
  function settlePublish(op: OperationStatus): void {
    publishing.value = false
    if (op.status === 'success' && op.result) {
      const r = op.result as {
        state: 'all_success' | 'partial_success'
        n_ok: number
        n_failed: number
        failure_detail?: string
        results: api.PlanRow[]
      }
      publishResult.value = {
        state: r.state,
        n_ok: r.n_ok,
        n_total: r.n_ok + r.n_failed,
        failure_detail: r.failure_detail,
        results: r.results,
      }
      publishOpId.value = null
    }
    // On failed/canceled: keep publishOpId so the page's OperationProgress
    // stays visible with the terminal error until re-publish or reset.
  }

  function reset(): void {
    urls.value = []
    config.value = defaultConfig()
    plans.value = []
    validated.value = []
    clearEdits()
    publishResult.value = null
    publishOpId.value = null
    publishing.value = false
  }

  return {
    urls,
    config,
    plans,
    validated,
    edits,
    effectivePlans,
    publishResult,
    availablePlatforms,
    platformsError,
    planning,
    validating,
    publishing,
    publishOpId,
    stage,
    busy,
    loadPlatforms,
    setUrls,
    runPlan,
    runValidate,
    runPublish,
    settlePublish,
    patchRow,
    reset,
  }
})
