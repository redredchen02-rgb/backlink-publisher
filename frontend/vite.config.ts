/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Plan 2026-06-18-002 U3 — single-origin Vue SPA.
//
// base '/app/' is used for BOTH dev and prod and for the router, so asset URLs,
// the dev server, and client routes all agree. The build lands OUTSIDE
// webui_app/static (in webui_app/spa_dist) on purpose: (1) Flask's
// _compute_asset_version walks static/ at boot — keeping the SPA bundle out of
// that tree avoids a meaningless re-stamp; (2) it cannot collide with Flask's
// /static route. Flask's /app/* catch-all serves files-or-index from spa_dist.
export default defineConfig({
  base: '/app/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: '../webui_app/spa_dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    // Dev: forward the API to Flask so the browser sees same-origin (no CORS),
    // mirroring the prod single-origin topology. The SPA only ever calls
    // relative /api/... paths.
    proxy: {
      '/api': { target: 'http://localhost:8888', changeOrigin: true },
    },
    // Allow importing the shared design tokens (webui_app/static/css/tokens.css)
    // which lives outside the frontend root.
    fs: { allow: ['..'] },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.spec.ts'],
  },
})
