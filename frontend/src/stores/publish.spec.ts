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
