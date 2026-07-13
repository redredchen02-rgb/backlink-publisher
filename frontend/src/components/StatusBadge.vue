<script setup lang="ts">
// StatusBadge — unified status → colour/label mapping — Plan 2026-07-09 (U3).
//
// Replaces the scattered hand-written `badge bg-*` snippets across pages with
// one component so every status reads consistently. Unknown statuses fall back
// to a neutral badge instead of a missing class.

const props = defineProps<{
  status: string | null | undefined
  label?: string
}>()

interface BadgeStyle {
  cls: string
  text: string
}

const MAP: Record<string, BadgeStyle> = {
  // operation statuses
  pending: { cls: 'bg-secondary', text: '排队中' },
  running: { cls: 'bg-primary', text: '进行中' },
  success: { cls: 'bg-success', text: '成功' },
  failed: { cls: 'bg-danger', text: '失败' },
  canceled: { cls: 'bg-dark', text: '已取消' },
  // campaign / queue / batch statuses
  completed: { cls: 'bg-success', text: '已完成' },
  draft_review: { cls: 'bg-info', text: '待审核' },
  processing: { cls: 'bg-primary', text: '处理中' },
  idle: { cls: 'bg-light text-dark', text: '待处理' },
  skipped: { cls: 'bg-warning', text: '已跳过' },
  // publish-history statuses
  published: { cls: 'bg-success', text: '已发布' },
  drafted: { cls: 'bg-info', text: '已草稿' },
  verified: { cls: 'bg-success', text: '已验证' },
  unverified: { cls: 'bg-warning', text: '未验证' },
}

const style = (): BadgeStyle => {
  const key = (props.status || '').toLowerCase()
  if (MAP[key]) return MAP[key]
  return { cls: 'bg-light text-dark', text: props.label || props.status || '未知' }
}

const resolved = style()
</script>

<template>
  <span class="badge" :class="resolved.cls" data-testid="status-badge">{{
    props.label || resolved.text
  }}</span>
</template>
