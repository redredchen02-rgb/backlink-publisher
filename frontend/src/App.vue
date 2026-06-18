<script setup lang="ts">
import { useThemeStore } from './stores/theme'

const theme = useThemeStore()
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <strong>Backlink Publisher 控台</strong>
      <button type="button" @click="theme.toggle()">
        主题：{{ theme.theme === 'dark' ? '深色' : '亮色' }}
      </button>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
