/**
 * CDN icon-font 用法防回归 guard — Plan 2026-07-06-005 W7(R7 / D9)。
 *
 * SPA 图标已统一为自托管 inline SVG 组件(components/Icon.vue),不再依赖
 * bootstrap-icons 的 CDN icon font。本测试扫描 frontend/src 下全部 .vue 源码,
 * 断言零 `class="bi bi-*"` 用法——一旦有人加回 icon-font 写法,v0.6.0 U8 移除
 * CDN 后该图标会静默消失,此 guard 让它在 CI 就红灯。
 *
 * 同 data-table-adoption.spec.ts 的「读源码文本 + regex」技术,无需 DOM 渲染。
 */

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, relative, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
// __dir = .../frontend/src/__tests__ → 扫描根 = .../frontend/src
const SRC_DIR = resolve(__dir, '..')

/** 递归收集 frontend/src 下全部 .vue 文件的绝对路径。 */
function collectVueFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...collectVueFiles(full))
    else if (entry.isFile() && entry.name.endsWith('.vue')) out.push(full)
  }
  return out
}

// 命中 class 属性(静态或 :class 绑定字符串)中作为独立 token 的 `bi bi-*` 组合,
// 例如 class="bi bi-shield-check" / class="x bi bi-y me-1"。
const BI_ICON_FONT_PATTERN = /class="[^"]*\bbi\s+bi-[a-z0-9-]+/

describe('no-cdn-icon-usage guard (W7)', () => {
  it('frontend/src 下没有任何 .vue 文件使用 icon-font 的 `bi bi-*` class', () => {
    const files = collectVueFiles(SRC_DIR)
    // 自检:扫描器确实在扫真实文件集(空集会让断言真空成立)。
    expect(files.length).toBeGreaterThan(0)

    const violations: string[] = []
    for (const file of files) {
      const text = readFileSync(file, 'utf8')
      const lines = text.split('\n')
      lines.forEach((line, i) => {
        if (BI_ICON_FONT_PATTERN.test(line)) {
          violations.push(
            `${relative(SRC_DIR, file)}:${i + 1} — ${line.trim()}(请改用 components/Icon.vue)`,
          )
        }
      })
    }

    expect(violations, `\n发现 CDN icon-font 用法:\n${violations.join('\n')}`).toEqual([])
  })
})
