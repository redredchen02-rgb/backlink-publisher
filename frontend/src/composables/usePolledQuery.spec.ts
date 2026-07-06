import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { computeBackoffIntervalMs, usePolledQuery } from './usePolledQuery'

describe('computeBackoffIntervalMs (pure)', () => {
  it('zero failures -> the base interval', () => {
    expect(computeBackoffIntervalMs(0, 1000, 8000)).toBe(1000)
  })

  it('doubles per consecutive failure', () => {
    expect(computeBackoffIntervalMs(1, 1000, 8000)).toBe(2000)
    expect(computeBackoffIntervalMs(2, 1000, 8000)).toBe(4000)
  })

  it('caps at maxIntervalMs', () => {
    expect(computeBackoffIntervalMs(10, 1000, 8000)).toBe(8000)
  })
})

describe('usePolledQuery integration', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    vi.useFakeTimers()
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function mountHarness(queryFn: () => Promise<{ done: boolean }>) {
    const Harness = defineComponent({
      setup() {
        const query = usePolledQuery({
          queryKey: ['harness'],
          queryFn,
          intervalMs: 1000,
          isTerminal: (data) => data?.done === true,
        })
        return () => h('div', query.data.value ? JSON.stringify(query.data.value) : '')
      },
    })
    return mount(Harness, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  }

  it('fetches on mount, then again after intervalMs', async () => {
    const queryFn = vi.fn().mockResolvedValue({ done: false })
    mountHarness(queryFn)
    await vi.advanceTimersByTimeAsync(0)
    expect(queryFn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(queryFn).toHaveBeenCalledTimes(2)
  })

  it('stops polling once isTerminal(data) is true', async () => {
    const queryFn = vi.fn().mockResolvedValue({ done: true })
    mountHarness(queryFn)
    await vi.advanceTimersByTimeAsync(0)
    expect(queryFn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(5000)
    // No further calls -- the first result was already terminal.
    expect(queryFn).toHaveBeenCalledTimes(1)
  })

  it('backs off the interval after a failed tick instead of retrying at the base rate', async () => {
    const queryFn = vi
      .fn()
      .mockResolvedValueOnce({ done: false })
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValue({ done: false })
    mountHarness(queryFn)

    await vi.advanceTimersByTimeAsync(0) // initial fetch: success
    expect(queryFn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000) // tick 2: fails
    expect(queryFn).toHaveBeenCalledTimes(2)

    // Base interval (1000ms) must NOT be enough to trigger tick 3 -- backoff
    // doubled it to 2000ms after the failure.
    await vi.advanceTimersByTimeAsync(1000)
    expect(queryFn).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(1000) // now at 2000ms since tick 2
    expect(queryFn).toHaveBeenCalledTimes(3)
  })
})
