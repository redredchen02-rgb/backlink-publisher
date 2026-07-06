<script setup lang="ts">
// Icon — Plan 2026-07-06-005 W7 (R7 / D9):自托管 inline SVG 图标组件,
// 取代 SPA 内对 bootstrap-icons CDN icon font 的 `bi bi-*` 依赖(离线可用)。
//
// SVG path 数据逐颗内联自 bootstrap-icons v1.11.0(MIT licence,
// https://github.com/twbs/icons)。只收录 SPA 实际用到的图标;新增用法时
// 在 ICONS 里补一条(从 bootstrap-icons 的 icons/<name>.svg 抄 path)。
//
// A11y 约定:默认装饰性(aria-hidden="true");传 `label` 时变语义图标
// (role="img" + aria-label)。尺寸 1em 随字级,fill=currentColor 随文字色
// (token 兼容,不引入任何自有颜色)。
import { computed, watch } from 'vue'

interface IconPath {
  d: string
  fillRule?: 'evenodd'
}

const ICONS: Record<string, IconPath[]> = {
  'box-arrow-up-right': [
    {
      d: 'M8.636 3.5a.5.5 0 0 0-.5-.5H1.5A1.5 1.5 0 0 0 0 4.5v10A1.5 1.5 0 0 0 1.5 16h10a1.5 1.5 0 0 0 1.5-1.5V7.864a.5.5 0 0 0-1 0V14.5a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-10a.5.5 0 0 1 .5-.5h6.636a.5.5 0 0 0 .5-.5z',
      fillRule: 'evenodd',
    },
    {
      d: 'M16 .5a.5.5 0 0 0-.5-.5h-5a.5.5 0 0 0 0 1h3.793L6.146 9.146a.5.5 0 1 0 .708.708L15 1.707V5.5a.5.5 0 0 0 1 0v-5z',
      fillRule: 'evenodd',
    },
  ],
  'shield-check': [
    {
      d: 'M5.338 1.59a61.44 61.44 0 0 0-2.837.856.481.481 0 0 0-.328.39c-.554 4.157.726 7.19 2.253 9.188a10.725 10.725 0 0 0 2.287 2.233c.346.244.652.42.893.533.12.057.218.095.293.118a.55.55 0 0 0 .101.025.615.615 0 0 0 .1-.025c.076-.023.174-.061.294-.118.24-.113.547-.29.893-.533a10.726 10.726 0 0 0 2.287-2.233c1.527-1.997 2.807-5.031 2.253-9.188a.48.48 0 0 0-.328-.39c-.651-.213-1.75-.56-2.837-.855C9.552 1.29 8.531 1.067 8 1.067c-.53 0-1.552.223-2.662.524zM5.072.56C6.157.265 7.31 0 8 0s1.843.265 2.928.56c1.11.3 2.229.655 2.887.87a1.54 1.54 0 0 1 1.044 1.262c.596 4.477-.787 7.795-2.465 9.99a11.775 11.775 0 0 1-2.517 2.453 7.159 7.159 0 0 1-1.048.625c-.28.132-.581.24-.829.24s-.548-.108-.829-.24a7.158 7.158 0 0 1-1.048-.625 11.777 11.777 0 0 1-2.517-2.453C1.928 10.487.545 7.169 1.141 2.692A1.54 1.54 0 0 1 2.185 1.43 62.456 62.456 0 0 1 5.072.56z',
    },
    {
      d: 'M10.854 5.146a.5.5 0 0 1 0 .708l-3 3a.5.5 0 0 1-.708 0l-1.5-1.5a.5.5 0 1 1 .708-.708L7.5 7.793l2.646-2.647a.5.5 0 0 1 .708 0z',
    },
  ],
  'exclamation-triangle-fill': [
    {
      d: 'M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z',
    },
  ],
}

const props = defineProps<{
  /** bootstrap-icons 图标名(不含 bi- 前缀),须已收录于 ICONS。 */
  name: string
  /** 传入则成为语义图标:role="img" + aria-label;不传则 aria-hidden。 */
  label?: string
}>()

const paths = computed<IconPath[] | undefined>(() => ICONS[props.name])

watch(
  () => props.name,
  (name) => {
    if (!ICONS[name]) {
      console.warn(`[Icon] 未知图标名:"${name}"(未收录于 Icon.vue 的 ICONS 表,渲染为空)`)
    }
  },
  { immediate: true },
)
</script>

<template>
  <svg
    v-if="paths"
    class="app-icon"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 16 16"
    width="1em"
    height="1em"
    fill="currentColor"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <path v-for="(p, i) in paths" :key="i" :d="p.d" :fill-rule="p.fillRule" />
  </svg>
</template>

<style scoped>
/* 对齐 bootstrap-icons icon font 的基线表现;颜色/尺寸全部继承文字。 */
.app-icon {
  display: inline-block;
  vertical-align: -0.125em;
  flex-shrink: 0;
}
</style>
