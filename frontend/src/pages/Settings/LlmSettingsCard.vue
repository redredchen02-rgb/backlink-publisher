<script setup lang="ts">
// AI integration card (Plan 2026-06-18-002 U7, settings section 2) — the LLM +
// image-gen config form (one save → /api/v1/settings/llm-config) plus the four
// diagnostics (LLM test-connection / test-generation, image-gen test / sample).
// Self-contained so SettingsPage stays a thin section host. Secrets follow the
// blank-preserve rule: the GET never returns the key (has_* booleans only), the
// inputs start blank, and a blank submit keeps the stored secret.
import { computed, reactive, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  getLlmConfig,
  saveLlmConfig,
  clearLlmConfig,
  testLlmConnection,
  testLlmGeneration,
  testImageGen,
  generateImageSample,
  type LlmDiagnostic,
  type ImageGenDiagnostic,
} from '../../api/settings'
import { useErrorToast } from '../../composables/useErrorToast'
import { useSnapshotDirty } from '../../composables/useSnapshotDirty'
import { useSettingsForm } from '../../composables/useSettingsForm'
import StateBlock from '../../components/StateBlock.vue'

type FourState = 'loading' | 'empty' | 'error' | 'ready'

const { toastError } = useErrorToast()
// Plan 2026-07-06-005 W1 (D15): edit-surface query (hydrates `form`) —
// window-focus refetch explicitly OFF. See
// docs/audits/2026-07-06-webui-refresh-inventory.md.
const query = useQuery({
  queryKey: ['settings', 'llm'],
  queryFn: getLlmConfig,
  refetchOnWindowFocus: false,
})

const form = reactive({
  endpoint: '',
  api_key: '',
  model: '',
  temperature: 0.7,
  system_prompt: '',
  use_article_gen: false,
  article_system_prompt: '',
  use_image_gen: false,
  image_gen_api_key: '',
  image_gen_endpoint: '',
  image_gen_model: '',
  image_gen_banner_size: '1200x630',
})
const hasApiKey = ref(false)
const hasImageGenApiKey = ref(false)

// Plan 2026-07-06-005 W2 — hydration-overwrite fix: while the operator has
// unsaved edits anywhere in this (largest) form, a query refetch must not
// clobber them. `markClean()` re-baselines right after a hydration actually
// runs, including the one echoing this card's own successful save/clear
// (where the two API-key fields get programmatically blanked).
const { dirty, markClean } = useSnapshotDirty('settings-llm', '进阶 LLM 整合', () => form)

// Plan 2026-07-06-005 W6 — shared save convention: 422 renders inline (best-
// effort field attribution via regex — see useSettingsForm's docstring),
// success toast + this card's `markClean()`, per-card `saving` busy (shared
// by save AND clear, same as before W6 — they're mutually-exclusive actions
// on one card). Declaration order matters: the `image_gen_*` patterns are
// tried first so a detail like "image_gen_endpoint 必须以 https:// 开头"
// attributes to the image-gen field, not the plain `endpoint` one below it.
const { saving, formError, fieldErrors, run } = useSettingsForm(
  markClean,
  {
    image_gen_endpoint: /image[_ ]gen(eration)?[_ ]?endpoint/i,
    image_gen_api_key: /image[_ ]gen(eration)?[_ ]?api[_ ]?key/i,
    image_gen_model: /image[_ ]gen(eration)?[_ ]?model/i,
    endpoint: /\bendpoint\b/i,
    api_key: /api[_ ]?key/i,
    model: /\bmodel\b/i,
  },
  'settings.llm',
)

watch(
  () => query.data.value,
  (d) => {
    if (!d) return
    if (dirty.value) return
    form.endpoint = d.endpoint
    form.model = d.model
    form.temperature = d.temperature
    form.system_prompt = d.system_prompt
    form.article_system_prompt = d.article_system_prompt
    form.use_article_gen = d.use_article_gen
    form.use_image_gen = d.use_image_gen
    form.image_gen_endpoint = d.image_gen_endpoint
    form.image_gen_model = d.image_gen_model
    form.image_gen_banner_size = d.image_gen_banner_size
    hasApiKey.value = d.has_api_key
    hasImageGenApiKey.value = d.has_image_gen_api_key
    // secrets intentionally stay blank — never hydrated from the server.
    markClean()
  },
  { immediate: true },
)

const state = computed<FourState>(() => {
  if (query.isPending.value) return 'loading'
  if (query.isError.value) return 'error'
  return 'ready'
})

const testingConn = ref(false)
const testingGen = ref(false)
const testingImg = ref(false)
const generatingImg = ref(false)
const connResult = ref<LlmDiagnostic | null>(null)
const genResult = ref<LlmDiagnostic | null>(null)
const imgResult = ref<ImageGenDiagnostic | null>(null)
const sampleResult = ref<ImageGenDiagnostic | null>(null)


async function onSave(): Promise<void> {
  const result = await run(
    () =>
      saveLlmConfig({
        endpoint: form.endpoint,
        api_key: form.api_key,
        model: form.model,
        temperature: Number(form.temperature),
        system_prompt: form.system_prompt,
        use_article_gen: form.use_article_gen,
        article_system_prompt: form.article_system_prompt,
        use_image_gen: form.use_image_gen,
        image_gen_api_key: form.image_gen_api_key,
        image_gen_endpoint: form.image_gen_endpoint,
        image_gen_model: form.image_gen_model,
        image_gen_banner_size: form.image_gen_banner_size,
      }),
    {
      successMessage: 'LLM 设定已保存',
      onSuccess: () => {
        form.api_key = ''
        form.image_gen_api_key = ''
      },
    },
  )
  if (result) await query.refetch()
}

async function onClear(): Promise<void> {
  const result = await run(() => clearLlmConfig(), {
    successMessage: 'LLM 配置已清除',
    onSuccess: () => {
      form.api_key = ''
      form.image_gen_api_key = ''
      connResult.value = genResult.value = null
      imgResult.value = sampleResult.value = null
    },
  })
  if (result) await query.refetch()
}

async function onTestConnection(): Promise<void> {
  if (testingConn.value) return
  testingConn.value = true
  connResult.value = null
  try {
    connResult.value = await testLlmConnection({
      endpoint: form.endpoint,
      api_key: form.api_key,
      model: form.model,
    })
  } catch (e) {
    toastError(e)
  } finally {
    testingConn.value = false
  }
}

async function onTestGeneration(): Promise<void> {
  if (testingGen.value) return
  testingGen.value = true
  genResult.value = null
  try {
    genResult.value = await testLlmGeneration({ test_title: '测试标题' })
  } catch (e) {
    toastError(e)
  } finally {
    testingGen.value = false
  }
}

async function onTestImageGen(): Promise<void> {
  if (testingImg.value) return
  testingImg.value = true
  imgResult.value = null
  try {
    imgResult.value = await testImageGen()
  } catch (e) {
    toastError(e)
  } finally {
    testingImg.value = false
  }
}

async function onGenerateSample(): Promise<void> {
  if (generatingImg.value) return
  generatingImg.value = true
  sampleResult.value = null
  try {
    sampleResult.value = await generateImageSample({})
  } catch (e) {
    toastError(e)
  } finally {
    generatingImg.value = false
  }
}

const connClass = computed(() => (connResult.value?.status === 'ok' ? 'ok' : 'bad'))
const genClass = computed(() => (genResult.value?.status === 'ok' ? 'ok' : 'bad'))
</script>

<template>
  <section class="card" aria-labelledby="ai-h">
    <h2 id="ai-h">进阶 LLM 整合（可选）</h2>
    <p class="muted">支持所有 OpenAI 兼容 API。配好连接后，全文生成 / AI 封面图可独立启用。</p>

    <StateBlock :state="state" :error="query.error.value" @retry="query.refetch()">
      <form @submit.prevent="onSave">
        <!-- ① connection -->
        <fieldset class="grp">
          <legend>① 连接配置</legend>
          <label for="llm-ep">LLM Endpoint</label>
          <input id="llm-ep" v-model="form.endpoint" type="text" placeholder="https://api.openai.com/v1" />
          <small v-if="fieldErrors.endpoint" class="field-error" data-test="err-endpoint">
            {{ fieldErrors.endpoint }}
          </small>
          <div class="row2">
            <div class="field">
              <label for="llm-key">API Key</label>
              <input
                id="llm-key"
                v-model="form.api_key"
                type="password"
                autocomplete="off"
                :placeholder="hasApiKey ? '已设置（留空保留现值）' : 'sk-…'"
              />
              <small v-if="fieldErrors.api_key" class="field-error" data-test="err-api-key">
                {{ fieldErrors.api_key }}
              </small>
            </div>
            <div class="field">
              <label for="llm-model">Model</label>
              <input id="llm-model" v-model="form.model" type="text" placeholder="gpt-4o" />
              <small v-if="fieldErrors.model" class="field-error" data-test="err-model">
                {{ fieldErrors.model }}
              </small>
            </div>
          </div>
          <div class="diag">
            <button type="button" :disabled="testingConn" @click="onTestConnection">
              {{ testingConn ? '测试中…' : '测试连接' }}
            </button>
            <span v-if="connResult" class="diag__r" :class="connClass">
              {{ connResult.status === 'ok' ? '连接成功' : connResult.message || connResult.reason }}
              <template v-if="connResult.models?.length">· {{ connResult.models.length }} 个模型</template>
            </span>
          </div>
        </fieldset>

        <!-- ② feature toggles -->
        <fieldset class="grp">
          <legend>② 功能开关</legend>
          <label class="switch">
            <input v-model="form.use_article_gen" type="checkbox" />
            AI 全文生成（每次发布自动生成完整正文）
          </label>
          <div v-if="form.use_article_gen" class="indent">
            <label for="art-p">文章生成提示词（留空用内置默认）</label>
            <textarea id="art-p" v-model="form.article_system_prompt" rows="3" />
            <div class="diag">
              <button type="button" :disabled="testingGen" @click="onTestGeneration">
                {{ testingGen ? '生成中…' : '测试生成' }}
              </button>
              <span v-if="genResult" class="diag__r" :class="genClass">
                {{ genResult.status === 'ok' ? (genResult.result || '生成成功') : genResult.message }}
              </span>
            </div>
          </div>

          <label class="switch">
            <input v-model="form.use_image_gen" type="checkbox" />
            AI 封面图生成（自动生成 1200×630 OG banner）
          </label>
          <div v-if="form.use_image_gen" class="indent">
            <div class="field">
              <label for="img-key">Image API Key</label>
              <input
                id="img-key"
                v-model="form.image_gen_api_key"
                type="password"
                autocomplete="off"
                :placeholder="hasImageGenApiKey ? '已设置（留空保留现值）' : '输入 Image Gen API Key'"
              />
              <small v-if="fieldErrors.image_gen_api_key" class="field-error" data-test="err-img-key">
                {{ fieldErrors.image_gen_api_key }}
              </small>
            </div>
            <div class="row2">
              <div class="field">
                <label for="img-ep">Image Endpoint</label>
                <input id="img-ep" v-model="form.image_gen_endpoint" type="text" placeholder="https://api.example.com/v1" />
                <small v-if="fieldErrors.image_gen_endpoint" class="field-error" data-test="err-img-ep">
                  {{ fieldErrors.image_gen_endpoint }}
                </small>
              </div>
              <div class="field">
                <label for="img-model">Image Model</label>
                <input id="img-model" v-model="form.image_gen_model" type="text" placeholder="gpt-image-1" />
                <small v-if="fieldErrors.image_gen_model" class="field-error" data-test="err-img-model">
                  {{ fieldErrors.image_gen_model }}
                </small>
              </div>
              <div class="field field--sm">
                <label for="img-size">尺寸</label>
                <input id="img-size" v-model="form.image_gen_banner_size" type="text" placeholder="1200x630" />
              </div>
            </div>
            <div class="diag">
              <button type="button" :disabled="testingImg" @click="onTestImageGen">
                {{ testingImg ? '测试中…' : '测试图像连接' }}
              </button>
              <button type="button" :disabled="generatingImg" @click="onGenerateSample">
                {{ generatingImg ? '生成中…' : '生成示例图' }}
              </button>
              <span v-if="imgResult" class="diag__r" :class="imgResult.ok ? 'ok' : 'bad'">
                {{ imgResult.ok ? (imgResult.note || '连接成功') : imgResult.error }}
                <template v-if="imgResult.frw_credits_remaining != null">
                  · 余额 {{ imgResult.frw_credits_remaining }}
                </template>
              </span>
            </div>
            <div v-if="sampleResult" class="sample">
              <img v-if="sampleResult.ok && sampleResult.data_url" :src="sampleResult.data_url" alt="生成的示例封面图" />
              <span v-else class="diag__r bad">{{ sampleResult.error }}</span>
            </div>
          </div>
        </fieldset>

        <!-- ③ advanced -->
        <details class="grp">
          <summary>③ 进阶调优（temperature、锚文本提示词）</summary>
          <label for="temp">Temperature（创造力）：{{ form.temperature }}</label>
          <input id="temp" v-model.number="form.temperature" type="range" min="0" max="2" step="0.1" />
          <label for="sys-p">锚文本生成提示词（留空用内置默认）</label>
          <textarea id="sys-p" v-model="form.system_prompt" rows="4" />
        </details>

        <p v-if="formError" class="form-error" data-test="llm-form-error">{{ formError }}</p>
        <div class="actions">
          <button type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存 LLM 设定' }}</button>
          <button type="button" class="danger" :disabled="saving" @click="onClear">清除配置</button>
        </div>
      </form>
    </StateBlock>
  </section>
</template>

<style scoped>
.card {
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
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
.grp {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 0.85rem;
  margin: 0.85rem 0;
}
.grp legend,
.grp > summary {
  font-weight: 600;
  font-size: var(--text-lg);
  padding: 0 0.4rem;
}
.grp > summary {
  cursor: pointer;
  user-select: none;
}
label {
  display: block;
  font-size: var(--text-sm);
  margin: 0.5rem 0 0.2rem;
}
input[type='text'],
input[type='password'],
textarea {
  width: 100%;
  box-sizing: border-box;
  padding: var(--control-pad-y) var(--control-pad-x);
}
textarea {
  font-family: var(--font-mono, monospace);
  font-size: var(--text-sm);
}
.row2 {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.field {
  flex: 1 1 12rem;
}
.field--sm {
  flex: 0 1 6rem;
}
.switch {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  font-size: var(--text-base);
}
.indent {
  padding-left: 1rem;
  border-left: 2px solid var(--border);
  margin: 0.5rem 0 0.5rem 0.4rem;
}
.diag {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.6rem;
}
.diag__r {
  font-size: var(--text-sm);
}
.diag__r.ok {
  color: var(--success);
}
.diag__r.bad {
  color: var(--danger);
}
.sample img {
  margin-top: 0.6rem;
  max-width: 100%;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
}
.actions {
  display: flex;
  gap: 0.6rem;
  margin-top: 1rem;
}
.actions .danger {
  color: var(--danger);
}
.field-error,
.form-error {
  color: var(--danger);
  font-size: var(--text-sm);
  margin: 0.25rem 0 0;
}
</style>
