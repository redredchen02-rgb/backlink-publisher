// Onboarding wizard store (Plan 2026-07-09-001). Pinia setup store.
//
// Holds the wizard's open/closed UI state and a derived view of the server's
// onboarding status. Step completion is computed backend-side from real system
// state, so this store only mirrors it. `closedThisSession` prevents the
// auto-open watch from re-popping the guide on every background refetch while
// the operator is still mid-setup and has chosen to skip for now.

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  dismissOnboarding,
  getOnboardingStatus,
  type OnboardingStatus,
  type OnboardingStep,
} from '../api/onboarding'

export const useOnboardingStore = defineStore('onboarding', () => {
  const queryClient = useQueryClient()
  const open = ref(false)
  // Set once the operator closes (skips) the guide this session so the
  // auto-open watch doesn't re-pop it on subsequent refetches while incomplete.
  const closedThisSession = ref(false)

  const statusQuery = useQuery({
    queryKey: ['onboarding', 'status'],
    queryFn: getOnboardingStatus,
    staleTime: 30_000,
  })

  const status = computed<OnboardingStatus | null>(() => statusQuery.data.value ?? null)
  const dismissed = computed(() => status.value?.dismissed ?? false)
  const allDone = computed(() => status.value?.all_done ?? false)
  const steps = computed<OnboardingStep[]>(() => status.value?.steps ?? [])
  const showWizard = computed(
    () => !statusQuery.isPending.value && !dismissed.value && !allDone.value,
  )

  function openWizard() {
    closedThisSession.value = false
    open.value = true
  }
  function closeWizard() {
    closedThisSession.value = true
    open.value = false
  }
  async function dismiss() {
    await dismissOnboarding()
    closedThisSession.value = true
    open.value = false
    await queryClient.invalidateQueries({ queryKey: ['onboarding', 'status'] })
  }
  return { open, status, dismissed, allDone, steps, showWizard, openWizard, closeWizard, dismiss }
})
