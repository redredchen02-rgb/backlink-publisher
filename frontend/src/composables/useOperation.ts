// useOperation — poll a single async operation by id — Plan 2026-07-09 (U1).
//
// Wraps usePolledQuery with the operation-specific terminal condition (an op
// stops polling once it reaches a terminal status). Mirrors the campaign
// progress composable in CampaignProgressPage.vue.
import { computed } from 'vue'
import { getOperation, type OperationStatus } from '../api/operations'
import { usePolledQuery } from './usePolledQuery'

const TERMINAL = new Set(['success', 'failed', 'canceled'])

export function useOperation(opId: () => string) {
  const query = usePolledQuery<OperationStatus>({
    queryKey: computed(() => ['operation', opId()]),
    queryFn: () => getOperation(opId()),
    intervalMs: 2000,
    isTerminal: (data) => TERMINAL.has(data?.status ?? ''),
    enabled: computed(() => !!opId()),
  })

  const op = computed(() => query.data.value ?? null)

  return { op, query }
}
