<script setup lang="ts">
// Optimization status — Plan P13 B2 (SPA migration).
import { computed, onMounted, ref } from 'vue'
import { fetchPlatforms, setWeight, unlockWeight, type PlatformWeight } from '../../api/optimizationStatus'
import StateBlock from '../../components/StateBlock.vue'

const platforms = ref<PlatformWeight[]>([])
const allPlatforms = ref<string[]>([])
const error = ref<Error | null>(null)
const loading = ref(true)
const message = ref('')
const messageType = ref<'success' | 'error' | ''>('')
const editingWeight = ref<string | null>(null)
const weightInput = ref('')
const setting = ref(false)

const blockState = computed<'loading' | 'empty' | 'error' | 'ready'>(() => {
  if (loading.value) return 'loading'
  if (error.value) return 'error'
  return 'ready'
})

const load = async () => {
  loading.value = true
  error.value = null
  try {
    const data = await fetchPlatforms()
    platforms.value = data.platforms
    allPlatforms.value = data.all_platforms
  } catch (e) {
    error.value = e instanceof Error ? e : new Error(String(e))
  } finally {
    loading.value = false
  }
}

const weightFor = (platform: string): number => {
  const p = platforms.value.find(p => p.platform === platform)
  return p?.weight ?? 0
}

const startEdit = (platform: string) => {
  editingWeight.value = platform
  weightInput.value = String(weightFor(platform))
}

const cancelEdit = () => {
  editingWeight.value = null
  weightInput.value = ''
}

const saveWeight = async (platform: string) => {
  const w = parseFloat(weightInput.value)
  if (isNaN(w) || w < 0) {
    message.value = '权重必须是一个非负数字'
    messageType.value = 'error'
    return
  }
  setting.value = true
  try {
    const result = await setWeight(platform, w)
    if (result.ok) {
      message.value = result.message ?? `已设置 ${platform} 权重为 ${w} 🔒`
      messageType.value = 'success'
      editingWeight.value = null
      await load()
    } else {
      message.value = result.error ?? '设置失败'
      messageType.value = 'error'
    }
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e)
    messageType.value = 'error'
  } finally {
    setting.value = false
  }
}

const doUnlock = async (platform: string) => {
  setting.value = true
  try {
    const result = await unlockWeight(platform)
    if (result.ok) {
      message.value = result.message ?? `已解锁 ${platform} — 规则可管理权重`
      messageType.value = 'success'
      await load()
    } else {
      message.value = result.error ?? '解锁失败'
      messageType.value = 'error'
    }
  } catch (e) {
    message.value = e instanceof Error ? e.message : String(e)
    messageType.value = 'error'
  } finally {
    setting.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="opt-status">
    <header class="opt-status__head">
      <h1>优化权重</h1>
      <button class="btn btn-sm btn-outline-secondary" @click="load" :disabled="loading">
        刷新
      </button>
    </header>

    <div v-if="message" :class="['alert', messageType === 'error' ? 'alert-danger' : 'alert-success', 'alert-dismissible']" role="alert">
      {{ message }}
      <button type="button" class="btn-close" aria-label="关闭" @click="message = ''" />
    </div>

    <StateBlock
      :state="blockState"
      :error="error"
      empty-text="暂无优化数据。"
      @retry="load"
    >
      <div class="data-table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>平台</th>
              <th>权重</th>
              <th>基准</th>
              <th>Delta%</th>
              <th>调整</th>
              <th>存活</th>
              <th>总计</th>
              <th>漂移</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in platforms" :key="p.platform">
              <td>
                <span class="fw-semibold">{{ p.platform }}</span>
                <span v-if="p.locked" class="badge bg-warning ms-1" title="已锁定">🔒</span>
              </td>
              <td class="col-num">
                <template v-if="editingWeight === p.platform">
                  <input
                    v-model="weightInput"
                    type="number"
                    step="0.01"
                    min="0"
                    class="form-control form-control-sm d-inline-block"
                    style="width: 80px"
                    :disabled="setting"
                  />
                  <button
                    class="btn btn-sm btn-success ms-1"
                    @click="saveWeight(p.platform)"
                    :disabled="setting"
                  >保存</button>
                  <button
                    class="btn btn-sm btn-outline-secondary ms-1"
                    @click="cancelEdit"
                    :disabled="setting"
                  >取消</button>
                </template>
                <template v-else>
                  {{ p.weight.toFixed(2) }}
                </template>
              </td>
              <td class="col-num">{{ (p.base ?? 0).toFixed(2) }}</td>
              <td class="col-num" :class="(p.delta_pct ?? 0) >= 0 ? 'text-success' : 'text-danger'">
                {{ (p.delta_pct ?? 0).toFixed(1) }}%
              </td>
              <td class="col-num">{{ p.adjustments ?? 0 }}</td>
              <td class="col-num">{{ p.alive ?? '—' }}</td>
              <td class="col-num">{{ p.total ?? '—' }}</td>
              <td class="col-num">{{ (p.drift ?? 0).toFixed(2) }}</td>
              <td>
                <div class="btn-group btn-group-sm">
                  <button
                    class="btn btn-outline-primary"
                    @click="startEdit(p.platform)"
                    :disabled="editingWeight !== null"
                    title="设置权重"
                  >设置</button>
                  <button
                    v-if="p.locked"
                    class="btn btn-outline-warning"
                    @click="doUnlock(p.platform)"
                    :disabled="setting"
                    title="解锁"
                  >解锁</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <details class="opt-status__all mt-3">
        <summary class="text-muted" style="cursor:pointer">所有已知平台 ({{ allPlatforms.length }})</summary>
        <div class="d-flex flex-wrap gap-1 mt-2">
          <span
            v-for="pl in allPlatforms"
            :key="pl"
            :class="['badge', platforms.some(p => p.platform === pl) ? 'bg-success' : 'bg-secondary']"
          >{{ pl }}</span>
        </div>
      </details>
    </StateBlock>
  </section>
</template>

<style scoped>
.opt-status {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.opt-status__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}
.opt-status__head h1 {
  margin: 0;
}
</style>
