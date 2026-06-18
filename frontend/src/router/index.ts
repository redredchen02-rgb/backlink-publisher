// Plan 2026-06-18-002 U3 — client router.
// Base '/app/' matches the Flask catch-all that serves the SPA; deep-link
// refreshes on /app/<route> are served index.html by Flask, then resolved here.
import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory('/app/'),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../pages/Home.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('../pages/NotFound.vue'),
    },
  ],
})
