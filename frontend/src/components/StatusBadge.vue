<script setup lang="ts">
import { computed } from 'vue'

export type Tone = 'neutral' | 'primary' | 'success' | 'danger' | 'warning' | 'info' | 'dark'

const props = defineProps<{
  status?: string | null
  label?: string
  /** Explicit tone override — for boolean/derived badges where no status string exists. */
  tone?: Tone
}>()

const MAP: Record<string, { tone: Tone; text: string }> = {
  // operation statuses
  pending: { tone: 'neutral', text: '排队中' },
  running: { tone: 'primary', text: '进行中' },
  success: { tone: 'success', text: '成功' },
  failed: { tone: 'danger', text: '失败' },
  canceled: { tone: 'dark', text: '已取消' },
  // campaign / queue / batch statuses
  completed: { tone: 'success', text: '已完成' },
  draft_review: { tone: 'info', text: '待审核' },
  processing: { tone: 'primary', text: '处理中' },
  idle: { tone: 'neutral', text: '待处理' },
  skipped: { tone: 'warning', text: '已跳过' },
  // publish-history statuses
  published: { tone: 'success', text: '已发布' },
  drafted: { tone: 'info', text: '已草稿' },
  verified: { tone: 'success', text: '已验证' },
  unverified: { tone: 'warning', text: '未验证' },
  // pr-queue statuses (Phase A)
  draft: { tone: 'info', text: '草稿' },
  sent: { tone: 'primary', text: '已发送' },
  won: { tone: 'success', text: '已赢得' },
  lost: { tone: 'danger', text: '已失去' },
  // error-report statuses (Phase A)
  open: { tone: 'danger', text: '待处理' },
  acknowledged: { tone: 'warning', text: '已确认' },
  resolved: { tone: 'success', text: '已解决' },
  // drafts/history statuses (Phase A)
  scheduled: { tone: 'info', text: '已排程' },
  deleted: { tone: 'dark', text: '已删除' },
}

const resolved = computed<{ tone: Tone; text: string }>(() => {
  const key = props.status?.toLowerCase()
  const hit = key ? MAP[key] : undefined
  if (props.tone) return { tone: props.tone, text: props.label ?? hit?.text ?? props.status ?? '未知' }
  if (hit) return { tone: hit.tone, text: props.label ?? hit.text }
  return { tone: 'neutral', text: props.label || props.status || '未知' }
})
</script>

<template>
  <span class="badge" :class="`badge--${resolved.tone}`" data-testid="status-badge">{{
    resolved.text
  }}</span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 0.1rem 0.55rem;
  border-radius: var(--radius-pill);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  line-height: var(--leading-tight);
  white-space: nowrap;
}
.badge--neutral { background: var(--surface-overlay); color: var(--text-secondary); }
/* --primary IS theme-overridden (light theme darkens it to sky-700 for
   contrast), so color-mix over it stays legible in both themes. */
.badge--primary { background: color-mix(in srgb, var(--primary) 18%, transparent); color: var(--primary); }
/* --success/--danger/--warning/--info must NOT be used as text color here --
   they have no light-theme override in tokens.css, so text set from them
   lands at ~2:1 contrast over the *-soft tint on a light background. The
   paired --*-soft (background) / --*-text (foreground) tokens exist
   specifically for badge/pill text and carry real light-theme values. */
.badge--success { background: var(--success-soft); color: var(--success-text); }
.badge--danger  { background: var(--danger-soft);  color: var(--danger-text); }
.badge--warning { background: var(--warning-soft); color: var(--warning-text); }
.badge--info    { background: var(--info-soft);    color: var(--info-text); }
.badge--dark    { background: var(--surface-overlay); color: var(--text-primary); }
</style>
