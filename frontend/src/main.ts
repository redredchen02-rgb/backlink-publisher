// Plan 2026-06-18-002 U3 — SPA entry.
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'

// Inherit the shipped dark-console design tokens (webui-console-redesign, shipped).
// Single source of truth for colours/spacing/typography — no CSS-in-JS.
import '../../webui_app/static/css/tokens.css'
import './styles/app.css'

import App from './App.vue'
import { router } from './router'

createApp(App)
  .use(createPinia())
  .use(router)
  .use(VueQueryPlugin)
  .mount('#app')
