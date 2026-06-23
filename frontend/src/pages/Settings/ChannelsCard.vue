<script setup lang="ts">
// Channel section (Plan 2026-06-18-002 U7, settings section 3) — slice 1 is the
// READ-ONLY binding-status overview, hydrated from GET /api/v1/settings/channels.
// Each row shows a channel's bind state / identity / dofollow / blockers. The
// per-auth-type binding FORMS (anon/token/token_fields/paste_blob/userpass) and
// the per-channel actions consume the already-migrated write endpoints in later
// slices; until then, binding edits stay on the legacy settings page.
import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { getChannels, type ChannelOverviewItem } from '../../api/settings'
import StateBlock from '../../components/StateBlock.vue'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const query = useQuery({ queryKey: ['settings', 'channels'], queryFn: getChannels })
const channels = computed<ChannelOverviewItem[]>(() => query.data.value?.channels ?? [])

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return channels.value.length ? 'ready' : 'empty'
})

function dofollowLabel(v: boolean | string | null): string {
  if (v === true) return 'dofollow'
  if (v === false) return 'nofollow'
  if (v === 'uncertain') return 'dofollow 存疑'
  return ''
}
function dofollowClass(v: boolean | string | null): string {
  if (v === true) return 'tag tag--ok'
  if (v === false) return 'tag tag--muted'
  if (v === 'uncertain') return 'tag tag--warn'
  return ''
}
</script>

<template>
  <section class="card" aria-labelledby="ch-h">
    <h2 id="ch-h">渠道绑定状态</h2>
    <p class="muted">
      各发布渠道的连接状态总览。绑定 / 改凭证见下方「渠道凭据绑定」及各渠道动作卡。
    </p>
    <StateBlock
      :state="state"
      :error="query.error.value"
      empty-text="无可用渠道。"
      @retry="query.refetch()"
    >
      <ul class="ch-list">
        <li v-for="c in channels" :key="c.slug" class="ch">
          <div class="ch__head">
            <strong>{{ c.display_name }}</strong>
            <span v-if="c.auth_type" class="tag tag--muted">{{ c.auth_type }}</span>
            <span class="tag" :class="c.bound ? 'tag--ok' : 'tag--muted'">
              {{ c.bound ? '已绑定' : '未绑定' }}
            </span>
            <span v-if="dofollowLabel(c.dofollow)" :class="dofollowClass(c.dofollow)">
              {{ dofollowLabel(c.dofollow) }}
            </span>
          </div>
          <div v-if="c.identity" class="ch__meta muted">身份：{{ c.identity }}</div>
          <ul v-if="c.blockers.length" class="ch__blockers">
            <li v-for="(b, i) in c.blockers" :key="i">{{ b }}</li>
          </ul>
        </li>
      </ul>
    </StateBlock>
  </section>
</template>

<style scoped>
.card {
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.25rem;
}
.card h2 {
  margin: 0 0 0.5rem;
  font-size: var(--text-xl);
}
.muted {
  color: var(--text-secondary);
  font-size: var(--text-base);
}
.ch-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.ch {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.6rem 0.85rem;
}
.ch__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.ch__meta {
  margin-top: 0.3rem;
}
.ch__blockers {
  margin: 0.4rem 0 0;
  padding-left: 1.1rem;
  color: var(--warning);
  font-size: var(--text-sm);
}
.tag {
  font-size: var(--text-xs);
  padding: 0.05rem 0.45rem;
  border-radius: 999px;
  border: 1px solid var(--border);
}
.tag--ok {
  color: var(--success);
  border-color: currentColor;
}
.tag--warn {
  color: var(--warning);
  border-color: currentColor;
}
.tag--muted {
  color: var(--text-secondary);
}
</style>
