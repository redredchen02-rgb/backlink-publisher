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
import { keepPreviousData, useQuery, type QueryKey, type UseQueryReturnType } from '@tanstack/vue-query'

export interface UsePolledQueryOptions<T> {
  queryKey: QueryKey
  queryFn: (context: { signal: AbortSignal }) => Promise<T>
  /** Poll interval (ms) while healthy (zero consecutive failures). */
  intervalMs: number
  /** Ceiling for the backoff-lengthened interval. Default: 8x intervalMs. */
  maxIntervalMs?: number
  /** When true for the current data, polling stops entirely (e.g. campaign done). */
  isTerminal?: (data: T | undefined) => boolean
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

  return useQuery({
    queryKey: opts.queryKey,
    queryFn: opts.queryFn,
    placeholderData: keepPreviousData, // no skeleton flash on each poll tick
    refetchInterval: (query) => {
      if (opts.isTerminal?.(query.state.data as T | undefined)) return false
      return computeBackoffIntervalMs(query.state.fetchFailureCount, opts.intervalMs, maxIntervalMs)
    },
  }) as UseQueryReturnType<T, Error>
}
