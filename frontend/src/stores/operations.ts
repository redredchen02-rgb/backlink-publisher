// Operations store — Plan 2026-07-09 (U1).
//
// The server (OperationSqliteStore) is the source of truth for async ops; this
// store only mirrors a lightweight `activeCount` so the sidenav badge can show
// how many operations are currently in flight without every component polling
// independently. OperationsPage polls the list and keeps this count fresh.

import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useOperationsStore = defineStore('operations', () => {
  const activeCount = ref(0)

  function setActiveCount(n: number): void {
    activeCount.value = Math.max(0, n)
  }

  return { activeCount, setActiveCount }
})
