import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../api/pipeline', () => ({
  planBacklinks: vi.fn(),
  validateBacklinks: vi.fn(),
  publishBacklinks: vi.fn(),
  boundPlatforms: vi.fn(),
}))

import * as api from '../api/pipeline'
import { usePublishStore } from './publish'

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('publish store — stage machine', () => {
  it('setUrls parses newline-separated input, trimming and dropping blanks', () => {
    const s = usePublishStore()
    s.setUrls('  https://a.com/ \n\n https://b.com/ \n   ')
    expect(s.urls).toEqual(['https://a.com/', 'https://b.com/'])
  })

  it('stage advances input → planned → validated → published', async () => {
    const s = usePublishStore()
    expect(s.stage).toBe('input')

    vi.mocked(api.planBacklinks).mockResolvedValue({ plans: [{ id: 'a' }] })
    s.setUrls('https://a.com/')
    await s.runPlan()
    expect(s.plans).toEqual([{ id: 'a' }])
    expect(s.stage).toBe('planned')
    expect(s.planning).toBe(false)

    vi.mocked(api.validateBacklinks).mockResolvedValue({ validated: [{ id: 'a', ok: true }] })
    await s.runValidate()
    expect(s.stage).toBe('validated')

    vi.mocked(api.publishBacklinks).mockResolvedValue({
      state: 'all_success',
      n_ok: 1,
      n_total: 1,
      results: [{ published_url: 'https://blog/x' }],
    })
    await s.runPublish()
    expect(s.publishResult?.state).toBe('all_success')
    expect(s.stage).toBe('published')
    expect(s.publishing).toBe(false)
  })

  it('runPlan passes the config-derived payload and invalidates downstream stages', async () => {
    const s = usePublishStore()
    s.config.platform = 'medium'
    s.config.tier1 = true
    s.validated = [{ stale: true }]
    s.publishResult = { state: 'all_success', n_ok: 1, n_total: 1, results: [] }
    vi.mocked(api.planBacklinks).mockResolvedValue({ plans: [{ id: 'fresh' }] })
    s.setUrls('https://a.com/')
    await s.runPlan()

    expect(api.planBacklinks).toHaveBeenCalledWith(
      expect.objectContaining({ urls: ['https://a.com/'], platform: 'medium' }),
    )
    expect(s.validated).toEqual([]) // re-planning clears downstream
    expect(s.publishResult).toBeNull()
  })

  it('runPublish refuses a double-submit while one is in flight', async () => {
    const s = usePublishStore()
    s.publishing = true // simulate an in-flight publish
    await s.runPublish()
    expect(api.publishBacklinks).not.toHaveBeenCalled()
  })

  it('loadPlatforms is tolerant of failure (keeps form usable)', async () => {
    const s = usePublishStore()
    vi.mocked(api.boundPlatforms).mockRejectedValue(new Error('boom'))
    await s.loadPlatforms()
    expect(s.availablePlatforms).toEqual([])

    vi.mocked(api.boundPlatforms).mockResolvedValue({
      platforms: [{ slug: 'blogger', display_name: 'Blogger' }],
    })
    await s.loadPlatforms()
    expect(s.availablePlatforms).toHaveLength(1)
  })

  it('loadPlatforms surfaces (but does not throw) the failure via platformsError, cleared on next success', async () => {
    const s = usePublishStore()
    expect(s.platformsError).toBeNull()

    const boom = new Error('boom')
    vi.mocked(api.boundPlatforms).mockRejectedValue(boom)
    await s.loadPlatforms()
    expect(s.platformsError).toBe(boom)

    vi.mocked(api.boundPlatforms).mockResolvedValue({
      platforms: [{ slug: 'blogger', display_name: 'Blogger' }],
    })
    await s.loadPlatforms()
    expect(s.platformsError).toBeNull()
  })

  it('reset returns to a clean input stage', () => {
    const s = usePublishStore()
    s.plans = [{ id: 'a' }]
    s.validated = [{ id: 'a' }]
    s.publishResult = { state: 'all_success', n_ok: 1, n_total: 1, results: [] }
    s.reset()
    expect(s.stage).toBe('input')
    expect(s.plans).toEqual([])
  })
})

describe('edits and effectivePlans', () => {
  it('effectivePlans equals validated when no edits', () => {
    const s = usePublishStore()
    s.validated = [{ id: 'a', title: 'A' }]
    expect(s.effectivePlans).toEqual([{ id: 'a', title: 'A' }])
  })

  it('patchRow merges only specified fields without clobbering others', () => {
    const s = usePublishStore()
    s.validated = [{ id: 'a', title: 'Original', content_markdown: 'Body' }]
    s.patchRow(0, { custom_title: 'New Title' })
    expect(s.effectivePlans[0].custom_title).toBe('New Title')
    expect(s.effectivePlans[0].title).toBe('Original')
    expect(s.effectivePlans[0].content_markdown).toBe('Body')
  })

  it('patchRow accumulates patches across calls (new reference each time)', () => {
    const s = usePublishStore()
    s.validated = [{ id: 'a' }]
    s.patchRow(0, { custom_title: 'X' })
    const after1 = s.edits[0]
    s.patchRow(0, { content_markdown: 'Y' })
    expect(s.edits[0]).not.toBe(after1)
    expect(s.edits[0]).toEqual({ custom_title: 'X', content_markdown: 'Y' })
  })

  it('runPublish uses effectivePlans not raw validated', async () => {
    const s = usePublishStore()
    s.validated = [{ id: 'a', title: 'Original' }]
    s.patchRow(0, { custom_title: 'Edited' })
    vi.mocked(api.publishBacklinks).mockResolvedValue({
      state: 'all_success',
      n_ok: 1,
      n_total: 1,
      results: [],
    })
    await s.runPublish()
    expect(api.publishBacklinks).toHaveBeenCalledWith(
      expect.objectContaining({
        plans: expect.arrayContaining([
          expect.objectContaining({ id: 'a', title: 'Original', custom_title: 'Edited' }),
        ]),
      }),
    )
  })

  it('reset clears edits', () => {
    const s = usePublishStore()
    s.validated = [{ id: 'a' }]
    s.patchRow(0, { custom_title: 'X' })
    s.reset()
    expect(s.edits).toEqual({})
  })

  it('runValidate success clears edits', async () => {
    const s = usePublishStore()
    s.validated = [{ id: 'old' }]
    s.patchRow(0, { custom_title: 'Stale' })
    s.plans = [{ id: 'a' }]
    vi.mocked(api.validateBacklinks).mockResolvedValue({ validated: [{ id: 'a' }] })
    await s.runValidate()
    expect(s.edits).toEqual({})
  })

  it('runValidate failure preserves edits', async () => {
    const s = usePublishStore()
    s.validated = [{ id: 'old' }]
    s.patchRow(0, { custom_title: 'Keep me' })
    s.plans = [{ id: 'a' }]
    vi.mocked(api.validateBacklinks).mockRejectedValue(new Error('network error'))
    try {
      await s.runValidate()
    } catch {}
    expect(s.edits[0]).toEqual({ custom_title: 'Keep me' })
  })

  it('runPlan clears edits', async () => {
    const s = usePublishStore()
    s.validated = [{ id: 'old' }]
    s.patchRow(0, { custom_title: 'Stale' })
    vi.mocked(api.planBacklinks).mockResolvedValue({ plans: [{ id: 'new' }] })
    s.setUrls('https://a.com/')
    await s.runPlan()
    expect(s.edits).toEqual({})
  })
})
