<script setup lang="ts">
// Monitoring aggregate dashboard — Plan 2026-06-18-002 U6 (inherits redesign R11).
//
// "Today's anomalies first": one fetch to /api/v1/monitor/summary returns cards
// already ranked server-side (danger → warning → ok → info); the SPA only
// displays them. Polled with TanStack Query + keepPreviousData so each tick does
// NOT flash the loading skeleton (the four-state 'stale' convention).
//
// Dual-stack wayfinding: each card's deep_link / action.href is a legacy Jinja
// page, so they are plain <a href> (full navigation OUT of the SPA, marked ↪) —
// not RouterLinks — until those pages are migrated.
//
// Plan 2026-07-06-004 Unit 6 turns this from a read-only card list into an
// interactive dashboard: hybrid cards (error_reports/schedule_queue) expand to
// show their first-N `items` with per-item actions; credentials/keepalive get
// in-place action buttons; every action shows its own inline busy/error state
// (never a full-page overlay) and writes its result straight into the
// ['monitor-summary'] query cache rather than waiting for the next poll tick.
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  monitorSummary, retryQueueTask, verifyChannel,
  type MonitorCard, type MonitorCardItem, type MonitorSummary,
} from '../../api/monitor'
import { updateErrorReport } from '../../api/errorReports'
import { startRecheck, pollRecheck } from '../../api/keepAlive'
import { classifyError } from '../../lib/errors'
import StateBlock from '../../components/StateBlock.vue'
import { useNotificationsStore } from '../../stores/notifications'

// R12/K10: shortened from the original 30s now that Unit 2's 4s server-side
// TTL cache on _collect_subsystem_status() makes a tighter poll cheap — a
// burst of concurrent polls/tabs within the TTL window still collapses onto
// one real backend query.
const POLL_MS = 15_000

const MONITOR_KEY = ['monitor-summary'] as const

// Flash-message bridge (Plan 2026-07-06-004 Unit 5): checkpoint.py/drafts.py
// (and anything else redirecting to bare '/') carry flash_type/flash_msg
// through main.py's '/' → '/app/' redirect (Unit 4) as query params on this,
// the new homepage. Read once on mount, surface as a toast, then strip the
// two params from the URL so a refresh doesn't re-show the same toast.
// `tab`/`campaign_id` are deliberately NOT read here — legacy-only params,
// out of scope for the new homepage (see plan's Scope Boundaries).
//
// DO NOT TOUCH (Unit 5) — this block must survive Unit 6's edits unchanged.
const route = useRoute()
const router = useRouter()
const notifications = useNotificationsStore()

// Independent client-side safety net — mirrors webui_app/helpers/security.py's
// _FLASH_MSG_MAX_LEN cap. Don't fully trust that the server-side sanitizer
// always ran (e.g. a future call site that forgets to use it); strip control
// characters and cap length so a pathological flash_msg can't break toast
// layout.
const FLASH_MSG_MAX_LEN = 200

function firstQueryValue(v: unknown): string {
  const s = Array.isArray(v) ? v[0] : v
  return typeof s === 'string' ? s : ''
}

function sanitizeFlashMsg(raw: string): string {
  // Strip C0/C1 control characters (CR/LF/tabs included) and cap length.
  return raw.replace(/[\x00-\x1F\x7F-\x9F]/g, ' ').trim().slice(0, FLASH_MSG_MAX_LEN)
}

onMounted(() => {
  const flashMsg = sanitizeFlashMsg(firstQueryValue(route.query.flash_msg))
  const flashType = firstQueryValue(route.query.flash_type)
  if (!flashMsg && !flashType) return

  notifications.pushFlash(flashMsg, flashType || undefined)

  // Clear flash_type/flash_msg from the query string so a page refresh
  // doesn't re-trigger the same toast; leave any other query params intact.
  const { flash_type: _flashType, flash_msg: _flashMsg, ...rest } = route.query
  router.replace({ query: rest })
})
// END flash-message bridge (Unit 5) — Unit 6 code resumes below.

const qc = useQueryClient()

const query = useQuery({
  queryKey: MONITOR_KEY,
  queryFn: monitorSummary,
  refetchInterval: POLL_MS,
  placeholderData: keepPreviousData, // don't flash the skeleton on each poll tick
})

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  // Zero cards only happens when the aggregator itself failed (degraded). All-OK
  // still returns cards — "no anomalies" is conveyed by the header banner.
  if ((query.data.value?.cards.length ?? 0) === 0) return 'empty'
  return 'ready'
})

const cards = computed(() => query.data.value?.cards ?? [])
const anomalyCount = computed(() => query.data.value?.anomaly_count ?? 0)
const degraded = computed(() => query.data.value?.degraded ?? false)

// ── Accessibility helpers (R17) ──────────────────────────────────────────────

const SEVERITY_LABELS: Record<string, string> = {
  danger: '严重', warning: '警告', ok: '正常', info: '信息',
}
function severityLabel(sev: string): string {
  return SEVERITY_LABELS[sev] ?? sev
}

const SCHEDULE_QUEUE_STATUS_LABELS: Record<string, string> = {
  overdue: '卡住排程', upcoming: '即将发布', unscheduled: '排程时间不明',
  pending: '待重试', failed: '重试失败', other: '状态异常',
}
function scheduleQueueStatusLabel(status: string | undefined): string {
  if (!status) return ''
  return SCHEDULE_QUEUE_STATUS_LABELS[status] ?? status
}

function isHybrid(card: MonitorCard): boolean {
  return card.items !== undefined
}

// ── Expand/collapse (hybrid cards only; collapsed by default) ───────────────

const expandedCards = ref<Record<string, boolean>>({})
function toggleExpanded(cardKey: string): void {
  expandedCards.value[cardKey] = !expandedCards.value[cardKey]
}

// ── Per-item / per-channel inline busy+error state ───────────────────────────
// Record<string,...> maps keyed by a composite id — NOT one dashboard-wide
// busy flag — so one item/channel's in-flight action never disables another.

const itemBusy = ref<Record<string, boolean>>({})
const itemError = ref<Record<string, string>>({})
function itemKey(cardKey: string, itemId: string): string {
  return `${cardKey}:${itemId}`
}

const verifyBusy = ref<Record<string, boolean>>({})
const verifyError = ref<Record<string, string>>({})

const keepaliveBusy = ref(false)
const keepaliveError = ref('')
let keepaliveTimer: ReturnType<typeof setTimeout> | null = null
onUnmounted(() => {
  if (keepaliveTimer) clearTimeout(keepaliveTimer)
})

// ── Focus management (accessibility, doc-review finding) ────────────────────
// After an item is removed from an expanded list, focus must move somewhere
// deliberate: the next sibling item's action button if one exists, otherwise
// the card's expand/collapse toggle (its "header" control) — never left to
// fall back to <body>.

const itemButtonEls: Record<string, HTMLButtonElement | null> = {}
// Fallback target when no next sibling exists: the card's own head/heading
// container (holds the severity dot + title). Given `tabindex="-1"` in the
// template so it's programmatically focusable without joining the normal
// Tab order. Deliberately NOT the expand/collapse toggle button — that
// button itself disappears from the DOM once a card's last item is removed
// (it's gated on items.length > 0), which would leave focus with nowhere to
// land right when it matters most (the last-item-removed case).
const cardHeadEls: Record<string, HTMLElement | null> = {}

function setItemButtonRef(cardKey: string, itemId: string, el: unknown): void {
  itemButtonEls[itemKey(cardKey, itemId)] = (el as HTMLButtonElement) ?? null
}
function setCardHeadRef(cardKey: string, el: unknown): void {
  cardHeadEls[cardKey] = (el as HTMLElement) ?? null
}

async function focusAfterRemoval(cardKey: string, nextItemId: string | null): Promise<void> {
  await nextTick()
  const target = nextItemId ? itemButtonEls[itemKey(cardKey, nextItemId)] : null
  ;(target ?? cardHeadEls[cardKey])?.focus()
}

// ── Error formatting ──────────────────────────────────────────────────────────
// These action errors originate from OUR OWN backend's small, fixed-vocabulary
// status strings (e.g. "任务不存在，可能已被处理") — not arbitrary/attacker
// text — so showing them verbatim (through Vue's auto-escaping interpolation,
// never v-html) is more useful to the operator than classifyError's generic
// category templates. A genuine network/timeout error (no server message)
// still falls back to those templates.
function describeActionError(e: unknown): string {
  if (e instanceof Error && e.message) return e.message
  return classifyError(e).message
}

/** Format + toast an action failure (screen-reader announcement goes through
 *  the existing Toast aria-live regions — no new per-card live region). */
function reportActionError(e: unknown): string {
  const msg = describeActionError(e)
  notifications.push(msg, 'error')
  return msg
}

// ── Query-cache write-through helpers ────────────────────────────────────────
// The query key is the WHOLE aggregate (['monitor-summary'], not a per-item
// key), so every write-through locally splices/updates the specific card's
// `items` array inside the cached MonitorSummary object.

function mutateCards(updater: (cards: MonitorCard[]) => MonitorCard[]): void {
  qc.setQueryData<MonitorSummary>(MONITOR_KEY, (old) => {
    if (!old) return old
    return { ...old, cards: updater(old.cards) }
  })
}

function removeCardItem(cardKey: string, itemId: string): void {
  mutateCards((cs) =>
    cs.map((c) =>
      c.key === cardKey && c.items
        ? { ...c, items: c.items.filter((it) => it.id !== itemId) }
        : c,
    ),
  )
}

function insertCardItem(cardKey: string, item: MonitorCardItem): void {
  mutateCards((cs) =>
    cs.map((c) => {
      if (c.key !== cardKey || !c.items) return c
      if (c.items.some((it) => it.id === item.id)) return c // already back — race-safe
      return { ...c, items: [item, ...c.items] }
    }),
  )
}

function patchCardItem(cardKey: string, itemId: string, patch: Partial<MonitorCardItem>): void {
  mutateCards((cs) =>
    cs.map((c) => {
      if (c.key !== cardKey || !c.items) return c
      return { ...c, items: c.items.map((it) => (it.id === itemId ? { ...it, ...patch } : it)) }
    }),
  )
}

// ── Action: mark-resolved (error-report items) — TERMINAL, has undo ──────────
// Mark-resolved removes the item from the list on success (it really is done)
// and shows a toast with an undo button that re-PATCHes status=open and
// re-inserts the item — no need to wait for the next poll tick either way.

async function markResolved(card: MonitorCard, item: MonitorCardItem): Promise<void> {
  const key = itemKey(card.key, item.id)
  if (itemBusy.value[key]) return
  itemBusy.value[key] = true
  itemError.value[key] = ''
  try {
    await updateErrorReport(item.id, { status: 'resolved' })
    const items = card.items ?? []
    const idx = items.findIndex((it) => it.id === item.id)
    const nextId = idx >= 0 ? (items[idx + 1]?.id ?? null) : null
    removeCardItem(card.key, item.id)
    notifications.push('已标记为已解决', 'success', 6000, undefined, {
      label: '撤销',
      onClick: () => undoResolve(card.key, item),
    })
    await focusAfterRemoval(card.key, nextId)
  } catch (e) {
    itemError.value[key] = reportActionError(e)
  } finally {
    itemBusy.value[key] = false
  }
}

async function undoResolve(cardKey: string, item: MonitorCardItem): Promise<void> {
  // Deliberately no busy/error state of its own — this is a best-effort,
  // transient client-side affordance (not a backend queue). If the toast has
  // already auto-dismissed, or the item's status changed via another path in
  // the meantime, this still either succeeds (server accepts the re-open) or
  // fails gracefully with its own toast; it never throws into the caller.
  try {
    const updated = await updateErrorReport(item.id, { status: 'open' })
    insertCardItem(cardKey, { ...item, status: updated.status })
    notifications.push('已撤销，重新标记为待处理', 'info')
  } catch (e) {
    notifications.push(`撤销失败：${describeActionError(e)}`, 'error')
  }
}

// ── Action: retry (queue_task items) — NOT terminal, no undo ─────────────────
// queue_store.get_runnable() selects status IN ('pending','failed') — after a
// successful retry the task is 'pending', which is STILL in that result set.
// Removing it locally would cause a disappear-then-reappear flicker on the
// very next poll tick. Instead: keep the item, just refresh its displayed
// status/detail text. It only leaves the list on a LATER poll, once the
// server's own get_runnable() result genuinely no longer includes it.

async function retryTask(card: MonitorCard, item: MonitorCardItem): Promise<void> {
  const key = itemKey(card.key, item.id)
  if (itemBusy.value[key]) return
  itemBusy.value[key] = true
  itemError.value[key] = ''
  try {
    const result = await retryQueueTask(item.id)
    const msg = result.flash_msg || '已重新排入队列，等待后台处理'
    patchCardItem(card.key, item.id, { status: 'pending', detail: msg })
    notifications.push(msg, 'success')
  } catch (e) {
    // e.g. a 404 on an already-vanished/processed task — inline text, never
    // a false "重试成功".
    itemError.value[key] = reportActionError(e)
  } finally {
    itemBusy.value[key] = false
  }
}

// ── Action: credential re-verify (sync; no undo) ─────────────────────────────

async function verifyChannelAction(channel: string): Promise<void> {
  if (verifyBusy.value[channel]) return
  verifyBusy.value[channel] = true
  verifyError.value[channel] = ''
  try {
    const result = await verifyChannel(channel)
    if (result.ok) {
      notifications.push(`${channel} 验证成功`, 'success')
      // Unit 3 already syncs the verdict into channel_status_store — refetch
      // the aggregate now rather than waiting up to POLL_MS for it to show.
      await qc.invalidateQueries({ queryKey: MONITOR_KEY })
    } else {
      const msg = result.blockers?.[0] || '验证失败，请重试'
      verifyError.value[channel] = msg
      notifications.push(msg, 'error')
    }
  } catch (e) {
    verifyError.value[channel] = reportActionError(e)
  } finally {
    verifyBusy.value[channel] = false
  }
}

// ── Action: keep-alive trigger recheck (job + poll; no undo) ─────────────────
// Reuses keepAlive.ts's existing startRecheck()/pollRecheck() — no new
// backend-calling code for this action, per the plan's explicit instruction.

async function triggerKeepaliveRecheck(): Promise<void> {
  if (keepaliveBusy.value) return
  keepaliveBusy.value = true
  keepaliveError.value = ''
  try {
    const result = await startRecheck()
    if (result.job_id) {
      pollKeepaliveJob(result.job_id)
    } else {
      keepaliveBusy.value = false
      notifications.push(result.message || '巡检已在进行中', 'info')
    }
  } catch (e) {
    keepaliveBusy.value = false
    keepaliveError.value = reportActionError(e)
  }
}

function pollKeepaliveJob(jobId: string): void {
  const poll = async () => {
    try {
      const status = await pollRecheck(jobId)
      if (status.status === 'completed' || status.status === 'done' || status.status === 'cancelled') {
        keepaliveBusy.value = false
        notifications.push(status.message || '巡检完成', 'success')
        await qc.invalidateQueries({ queryKey: MONITOR_KEY })
      } else if (status.status === 'error') {
        keepaliveBusy.value = false
        keepaliveError.value = status.message || '巡检出错'
      } else {
        keepaliveTimer = setTimeout(poll, 2000)
      }
    } catch {
      keepaliveTimer = setTimeout(poll, 2000)
    }
  }
  poll()
}
</script>

<template>
  <section class="monitor">
    <header class="monitor__head">
      <h1>监控聚合</h1>
      <p
        v-if="blockState === 'ready'"
        class="monitor__summary"
        role="status"
        aria-live="polite"
      >
        <span v-if="anomalyCount" class="anomaly">⚠ 今日 {{ anomalyCount }} 项异常</span>
        <span v-else class="ok">✓ 今日无异常</span>
        <span v-if="degraded" class="degraded-note">⚠ 部分数据源不可用，以上结果可能不完整</span>
      </p>
    </header>

    <StateBlock
      :state="blockState"
      :error="query.error.value"
      :is-fetching="blockState === 'ready' && query.isFetching.value"
      :stale="query.isStale.value"
      :last-updated="query.dataUpdatedAt.value ? new Date(query.dataUpdatedAt.value).toISOString() : undefined"
      empty-text="监控数据暂不可用，请稍后重试"
      @retry="query.refetch()"
    >
      <ul class="cards">
        <li v-for="card in cards" :key="card.key" class="card" :data-severity="card.severity">
          <div class="card__head" tabindex="-1" :ref="(el) => setCardHeadRef(card.key, el)">
            <span class="card__sev" :data-severity="card.severity" aria-hidden="true" />
            <span class="visually-hidden">{{ severityLabel(card.severity) }}</span>
            <span class="card__title">{{ card.title }}</span>
          </div>
          <p class="card__headline">{{ card.headline }}</p>
          <p v-if="card.detail" class="card__detail muted">{{ card.detail }}</p>

          <!-- Credentials: one re-verify button per failed channel -->
          <ul v-if="card.failed_channels && card.failed_channels.length" class="card__channel-actions">
            <li v-for="ch in card.failed_channels" :key="ch" class="channel-action">
              <button
                type="button"
                :disabled="verifyBusy[ch]"
                @click="verifyChannelAction(ch)"
              >{{ verifyBusy[ch] ? '验证中…' : `重新验证 ${ch}` }}</button>
              <span v-if="verifyError[ch]" class="field-error">{{ verifyError[ch] }}</span>
            </li>
          </ul>

          <!-- Keep-alive: trigger recheck -->
          <div v-if="card.key === 'keepalive'" class="card__inline-action">
            <button type="button" :disabled="keepaliveBusy" @click="triggerKeepaliveRecheck">
              {{ keepaliveBusy ? '巡检中…' : '触发巡检' }}
            </button>
            <span v-if="keepaliveError" class="field-error">{{ keepaliveError }}</span>
          </div>

          <!-- Hybrid cards (error_reports / schedule_queue): expand/collapse + per-item actions -->
          <template v-if="isHybrid(card)">
            <button
              v-if="(card.items?.length ?? 0) > 0"
              type="button"
              class="card__toggle"
              :aria-expanded="!!expandedCards[card.key]"
              @click="toggleExpanded(card.key)"
            >
              {{ expandedCards[card.key] ? '收起 ▲' : `展开 ${card.items!.length} 项 ▼` }}
            </button>

            <ul v-if="expandedCards[card.key] && card.items" class="card__items">
              <li
                v-for="item in card.items"
                :key="item.id"
                class="card-item"
                :data-item-type="item.item_type"
                :data-status="item.status"
              >
                <div class="card-item__row">
                  <span class="card-item__headline">{{ item.headline }}</span>
                  <span v-if="item.item_type !== 'error_report'" class="card-item__status">
                    {{ scheduleQueueStatusLabel(item.status) }}
                  </span>
                  <span v-else-if="item.occurrences" class="card-item__status">×{{ item.occurrences }}</span>
                </div>
                <p v-if="item.detail" class="card-item__detail muted">{{ item.detail }}</p>

                <div v-if="item.item_type === 'error_report'" class="card-item__actions">
                  <button
                    type="button"
                    :ref="(el) => setItemButtonRef(card.key, item.id, el)"
                    :disabled="itemBusy[itemKey(card.key, item.id)]"
                    @click="markResolved(card, item)"
                  >{{ itemBusy[itemKey(card.key, item.id)] ? '处理中…' : '标记已解决' }}</button>
                  <span v-if="itemError[itemKey(card.key, item.id)]" class="field-error">
                    {{ itemError[itemKey(card.key, item.id)] }}
                  </span>
                </div>

                <div v-else-if="item.item_type === 'queue_task'" class="card-item__actions">
                  <button
                    type="button"
                    :ref="(el) => setItemButtonRef(card.key, item.id, el)"
                    :disabled="itemBusy[itemKey(card.key, item.id)]"
                    @click="retryTask(card, item)"
                  >{{ itemBusy[itemKey(card.key, item.id)] ? '重试中…' : '重试' }}</button>
                  <span v-if="itemError[itemKey(card.key, item.id)]" class="field-error">
                    {{ itemError[itemKey(card.key, item.id)] }}
                  </span>
                </div>
              </li>
            </ul>

            <a
              v-if="expandedCards[card.key] && card.action"
              class="card__action"
              :href="card.action.href"
            >{{ card.action.label }} ↪</a>
          </template>

          <div class="card__links">
            <a class="card__deep" :href="card.deep_link">深钻 ↪</a>
            <a v-if="card.action && !isHybrid(card)" class="card__action" :href="card.action.href">
              {{ card.action.label }} ↪
            </a>
          </div>
        </li>
      </ul>
    </StateBlock>
  </section>
</template>

<style scoped>
.monitor {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.monitor__head {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  flex-wrap: wrap;
}
.monitor__summary {
  margin: 0;
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}
.anomaly {
  color: var(--warning);
  font-weight: 600;
}
.ok {
  color: var(--success);
  font-weight: 600;
}
/* R11/R18: degraded must read as "can't confirm everything is fine", never
   as plain muted gray next to a green checkmark (which under-communicates
   the distinction). Distinct icon + warning color, not `.muted`. */
.degraded-note {
  color: var(--warning);
  font-weight: 600;
}
.cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: 0.75rem;
}
.card {
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: var(--radius-lg);
  padding: 0.75rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
/* R10: actionable (danger/warning) cards outweigh purely-informational ones —
   a heavier border-left rather than a new color system. */
.card[data-severity='danger'] {
  border-left-color: var(--danger);
  border-left-width: 5px;
}
.card[data-severity='warning'] {
  border-left-color: var(--warning);
  border-left-width: 5px;
}
.card[data-severity='ok'] {
  border-left-color: var(--success);
}
.card[data-severity='info'] {
  border-left-color: var(--primary);
}
.card__head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.card__sev {
  width: 0.6rem;
  height: 0.6rem;
  border-radius: 50%;
  background: var(--text-secondary);
}
.card__sev[data-severity='danger'] {
  background: var(--danger);
}
.card__sev[data-severity='warning'] {
  background: var(--warning);
}
.card__sev[data-severity='ok'] {
  background: var(--success);
}
.card__title {
  font-weight: 600;
}
.card__headline {
  margin: 0;
}
.card__links {
  display: flex;
  gap: 0.75rem;
  margin-top: 0.25rem;
  font-size: var(--text-base);
}
.card__channel-actions {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.channel-action,
.card__inline-action {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.card__toggle {
  align-self: flex-start;
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0.15rem 0.5rem;
  cursor: pointer;
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.card__items {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.card-item {
  border-top: 1px solid var(--border);
  padding-top: 0.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.card-item__row {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: baseline;
}
.card-item__headline {
  font-weight: 500;
}
.card-item__status {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}
.card-item__actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.field-error {
  color: var(--danger);
  font-size: var(--text-sm);
}
.muted {
  color: var(--text-secondary);
}
/* Standard clip-based visually-hidden utility — conveys severity as text to
   screen readers without visually duplicating the `.card__sev` dot (R17). */
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
