<script setup lang="ts">
// Publish-preset selector — Plan 2026-06-18-002 U7 (profiles frontend).
//
// A small controlled widget: load a saved profile into the host form (`apply`
// event), save the host's current config as a named preset, or delete one. It is
// decoupled from any specific page — the parent passes the live `current` values
// and applies the emitted profile itself, so the selector owns no form state.
//
// Replaces the legacy lib/profiles.js loadProfile/saveProfilePrompt wiring that
// lived on the server-rendered workbench. url_mode is part of a profile but has
// no workbench control, so saves omit it (the backend defaults it) and loads
// leave it to the parent to ignore.
import { computed, ref } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { deleteProfile, getProfiles, saveProfile, type Profile } from '../api/profiles'
import { ApiError } from '../api/client'
import { useNotificationsStore } from '../stores/notifications'

const props = defineProps<{
  current: { platform: string; language: string; publishMode: string }
}>()
const emit = defineEmits<{ apply: [Profile] }>()

const PROFILES_KEY = ['profiles']
const qc = useQueryClient()
const notify = useNotificationsStore()

const query = useQuery({ queryKey: PROFILES_KEY, queryFn: getProfiles })
const profiles = computed<Profile[]>(() => query.data.value?.items ?? [])

const selected = ref('')
const newName = ref('')
const busy = ref(false)

function onLoad(): void {
  const p = profiles.value.find((x) => x.name === selected.value)
  if (p) emit('apply', p)
}

async function onSave(): Promise<void> {
  const name = newName.value.trim()
  if (!name) {
    notify.push('请先填写预设名称', 'warning')
    return
  }
  if (busy.value) return
  busy.value = true
  try {
    const r = await saveProfile({
      name,
      platform: props.current.platform,
      language: props.current.language,
      publish_mode: props.current.publishMode,
    })
    qc.setQueryData(PROFILES_KEY, { items: r.items })
    selected.value = name
    newName.value = ''
    notify.push(`已保存预设：${name}`, 'info')
  } catch (e) {
    notify.push(e instanceof ApiError ? e.message : '保存预设失败', 'error')
  } finally {
    busy.value = false
  }
}

async function onDelete(): Promise<void> {
  const name = selected.value
  if (!name || busy.value) return
  busy.value = true
  try {
    const r = await deleteProfile(name)
    qc.setQueryData(PROFILES_KEY, { items: r.items })
    selected.value = ''
    notify.push(`已删除预设：${name}`, 'info')
  } catch (e) {
    notify.push(e instanceof ApiError ? e.message : '删除预设失败', 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="profile-selector">
    <label class="profile-selector__load">
      预设
      <select v-model="selected" :disabled="busy" aria-label="选择发布预设">
        <option value="">（未选择）</option>
        <option v-for="p in profiles" :key="p.name" :value="p.name">{{ p.name }}</option>
      </select>
    </label>
    <button type="button" :disabled="!selected || busy" @click="onLoad">载入</button>
    <button type="button" class="danger" :disabled="!selected || busy" @click="onDelete">删除</button>

    <span class="profile-selector__sep" aria-hidden="true">|</span>

    <label class="profile-selector__save">
      存为预设
      <input
        v-model="newName"
        type="text"
        placeholder="预设名称"
        aria-label="新预设名称"
        @keyup.enter="onSave"
      />
    </label>
    <button type="button" :disabled="busy" @click="onSave">保存</button>
  </div>
</template>

<style scoped>
.profile-selector {
  display: flex;
  flex-flow: row wrap;
  align-items: end;
  gap: 0.5rem;
}
.profile-selector label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.profile-selector__sep {
  color: var(--border);
  align-self: center;
}
.profile-selector .danger {
  color: var(--danger);
}
</style>
