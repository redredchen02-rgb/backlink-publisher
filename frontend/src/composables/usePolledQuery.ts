// Unified polling composable — Plan 2026-07-02-001 U5.
//
// Wraps vue-query's refetchInterval + keepPreviousData with the pieces every
// hand-rolled poller was missing: error backoff, terminal-state stop, and
// tab-hidden pause. Fixes the two existing anti-patterns this unit's plan
// named directly: KeepAlivePage.vue's un-backed-off 2s retry loop and
// CampaignProgressPage.vue's silent error swallowing on a failed poll tick.
//
// Tab-hidden pause is NOT custom logic here -- vue-query's own
// `refetchIntervalInBackground` defaults to false, and its focusManager
// already listens for `visibilitychange` (not just window focus/blur), so
// simply not setting that option to true is sufficient; see
// @tanstack/query-core's focusManager.ts.
//
// Unmount cancellation is likewise vue-query's own behavior: the interval
// stops the moment the component unmounts and the query observer is torn
// down, with no separate teardown needed here.
import type { ComputedRef } from 'vue'
import { keepPreviousData, useQuery, type QueryKey, type UseQueryReturnType } from '@tanstack/vue-query'

export interface UsePolledQueryOptions<T> {
  queryKey: QueryKey | ComputedRef<QueryKey>
  queryFn: (context: { signal: AbortSignal }) => Promise<T>
  /** Poll interval (ms) while healthy (zero consecutive failures). */
  intervalMs: number
  /** Ceiling for the backoff-lengthened interval. Default: 8x intervalMs. */
  maxIntervalMs?: number
  /** When true for the current data, polling stops entirely (e.g. campaign done). */
  isTerminal?: (data: T | undefined) => boolean
  /** Skip fetching/polling entirely while false (e.g. a required id is empty). */
  enabled?: boolean | ComputedRef<boolean>
}

/**
 * Pure backoff calculation, extracted so it's testable without a real
 * QueryClient/timers: 0 consecutive failures -> the base interval; each
 * additional failure doubles it, capped at maxIntervalMs.
 */
export function computeBackoffIntervalMs(
  consecutiveFailures: number,
  intervalMs: number,
  maxIntervalMs: number,
): number {
  if (!consecutiveFailures) return intervalMs
  return Math.min(intervalMs * 2 ** consecutiveFailures, maxIntervalMs)
}

export function usePolledQuery<T>(
  opts: UsePolledQueryOptions<T>,
): UseQueryReturnType<T, Error> {
  const maxIntervalMs = opts.maxIntervalMs ?? opts.intervalMs * 8

  // NOT query.state.fetchFailureCount: with retry:false (see below) that field
  // resets to 0 at the START of every fetch attempt and can only ever reach 1
  // by the time refetchInterval evaluates it -- verified empirically (a
  // sustained-failure integration probe against real @tanstack/query-core
  // showed backoff plateauing at 2x the base interval forever, never
  // escalating further, no matter how many consecutive poll ticks failed).
  //
  // Also NOT query.state.status: it is NOT a reliable "did this attempt just
  // fail" signal either -- for a query that has never succeeded, status cycles
  // pending -> error -> pending -> error per attempt (a real transition each
  // time), but once a query HAS succeeded at least once, status goes sticky at
  // 'error' across every subsequent failed background refetch (never
  // revisiting 'pending' in between) -- verified empirically, the two cases
  // behave differently. A transition-detector keyed on status therefore
  // escalates correctly for "never succeeded, fails from the start" but gets
  // stuck after the first failure for "succeeded once, then fails repeatedly"
  // -- the realistic KeepAlivePage/CampaignProgressPage case, since polling
  // always starts from a successful initial fetch.
  //
  // query.state.errorUpdateCount/dataUpdateCount are the reliable signal:
  // both increment by exactly 1 on every settle, in either case, regardless of
  // the query's prior history -- so a delta-based counter here tracks
  // consecutive failures correctly either way. Reset whenever the underlying
  // queryKey changes so one job's failure streak (KeepAlivePage's job-id-
  // scoped polls) can't leak into a freshly-started, unrelated job's backoff.
  let consecutiveFailures = 0
  let lastQueryKeyJson: string | undefined
  let lastErrorUpdateCount = 0
  let lastDataUpdateCount = 0

  return useQuery({
    queryKey: opts.queryKey,
    queryFn: opts.queryFn,
    enabled: opts.enabled ?? true,
    placeholderData: keepPreviousData, // no skeleton flash on each poll tick
    // computeBackoffIntervalMs (via refetchInterval) IS this composable's retry
    // mechanism -- TanStack Query's own default retry (3 attempts with its own
    // delay, before fetchFailureCount even reflects a failure) would otherwise
    // run underneath it, so a "failed tick" would really be up to 4 requests
    // before this composable's own backoff ever saw it.
    retry: false,
    refetchInterval: (query) => {
      if (opts.isTerminal?.(query.state.data)) return false

      const keyJson = JSON.stringify(query.queryKey)
      if (keyJson !== lastQueryKeyJson) {
        consecutiveFailures = 0
        lastErrorUpdateCount = query.state.errorUpdateCount
        lastDataUpdateCount = query.state.dataUpdateCount
        lastQueryKeyJson = keyJson
      }
      if (query.state.dataUpdateCount > lastDataUpdateCount) {
        consecutiveFailures = 0
      } else if (query.state.errorUpdateCount > lastErrorUpdateCount) {
        consecutiveFailures += query.state.errorUpdateCount - lastErrorUpdateCount
      }
      lastErrorUpdateCount = query.state.errorUpdateCount
      lastDataUpdateCount = query.state.dataUpdateCount

      return computeBackoffIntervalMs(consecutiveFailures, opts.intervalMs, maxIntervalMs)
    },
  })
}
