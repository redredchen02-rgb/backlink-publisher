// ESLint flat config — Plan 2026-07-02-001 U12.
// Minimal viable rule set per the plan: vue3 *essential* (correctness, not
// formatting) + typescript-eslint recommended, aligned with the strict
// tsconfig. Deliberately excludes vue's stylistic/formatting tiers — the repo
// has no formatter for .vue files and a mass reformat would churn every page
// while parallel branches are editing them. Zero-warning baseline is enforced
// in CI (frontend.yml lint step runs with --max-warnings 0); widen rules only
// with the codebase already clean.
import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

export default defineConfigWithVueTs(
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**'] },
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  {
    rules: {
      // Established single-word component names (Toast, StateBlock) predate
      // this config and are referenced across active branches — renaming them
      // here would collide with in-flight work for zero correctness gain.
      'vue/multi-word-component-names': 'off',
      // vue-tsc already enforces unused-vars via strict tsconfig; keep the
      // ESLint copy on so plain .js config files are covered too, but allow
      // the established `_`-prefix escape hatch.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },
)
