// Plan 2026-06-18-002 U3 — SPA entry.
// Plan 2026-07-01-002 U6 — wires 3 of the 5 Vue-stack error-capture hooks
// (app.config.errorHandler, the Pinia plugin, and the QueryCache/
// MutationCache onError pair); the other 2 (window listeners, router.onError)
// are installed from errorCapture.ts itself / router/index.ts.
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin, QueryClient, QueryCache, MutationCache } from '@tanstack/vue-query'

// Inherit the shipped dark-console design tokens (webui-console-redesign, shipped).
// Single source of truth for colours/spacing/typography — no CSS-in-JS.
import '../../webui_app/static/css/tokens.css'
import './styles/app.css'

import App from './App.vue'
import { router } from './router'
import { errorCapturePlugin } from './stores/errorCapturePlugin'
import {
  installGlobalErrorListeners,
  installVueErrorHandler,
  reportQueryError,
  reportMutationError,
} from './lib/errorCapture'

const pinia = createPinia()
// Hook 5 — every store's actions are observed for rejections that don't
// necessarily bubble to window.unhandledrejection (vuejs/pinia#576).
pinia.use(errorCapturePlugin)

// Hook 4 — TanStack Query v5 removed per-query `onError`; a query/mutation
// fetcher failure is stored on the query/mutation's own state instead of
// being re-thrown, so this is the only place that surface is observed.
// SECURITY: only the error + the query/mutation KEY are forwarded — never
// `variables` (a mutation's raw call arguments, which may carry a plaintext
// secret such as api/settings.ts's saveLlmConfig `api_key`).
//
// Plan 2026-07-06-005 W1 (D15) — refresh behavior, explicit not implicit.
// Before this unit the QueryClient had no `defaultOptions` at all, so every
// page silently inherited the library defaults (`staleTime: 0`,
// `refetchOnWindowFocus: true`). That implicit default was a common enabler
// of the Settings hydration-overwrite bug (W2) and other refetch surprises —
// see docs/audits/2026-07-06-webui-refresh-inventory.md for the full per-page
// audit. This block makes the site-wide contract explicit and
// name-checkable — see the guard test in
// frontend/src/__tests__/query-defaults.spec.ts.
//
// - `refetchOnWindowFocus: true` — kept ON (not silently disabled) and
//   written here so it is a decision, not an accident: most pages are
//   read-mostly dashboards that benefit from a focus-triggered refresh.
// - `staleTime: 30_000` — previously implicit 0 (always stale, so every
//   mount/focus fired a network call even for data fetched a moment ago).
//   30s matches the order of magnitude of MonitorDashboard's own 30s poll
//   interval and cuts redundant-refetch noise without materially staling any
//   page's data. Pages that need different freshness (Monitor's poll,
//   Schedule's explicit focus-refetch, the Settings edit surface's
//   frozen-on-focus contract) override this explicitly at the query
//   site — see the inventory doc for the full per-page list.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: true,
      staleTime: 30_000,
    },
  },
  queryCache: new QueryCache({
    onError: (error, query) => reportQueryError(error, query.queryKey),
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _onMutateResult, mutation) =>
      reportMutationError(error, mutation.options.mutationKey),
  }),
})

const app = createApp(App)

// Hook 2 — component render/lifecycle/watcher/directive errors.
installVueErrorHandler(app)
// Hook 1 — native window 'error' (capture phase) / 'unhandledrejection',
// for errors Vue never schedules and so never sees.
installGlobalErrorListeners()

app
  .use(pinia)
  .use(router)
  .use(VueQueryPlugin, { queryClient })
  .mount('#app')
