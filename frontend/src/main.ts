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
const queryClient = new QueryClient({
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
