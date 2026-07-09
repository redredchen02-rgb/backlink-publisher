import { describe, expect, it } from 'vitest'
import { classifyError } from './errors'

describe('classifyError', () => {
  it('TypeError -> network', () => {
    expect(classifyError(new TypeError('Failed to fetch')).category).toBe('network')
  })

  it('403 / 401 / 419 -> permission', () => {
    expect(classifyError({ status: 403 }).category).toBe('permission')
    expect(classifyError({ status: 401 }).category).toBe('permission')
    expect(classifyError({ status: 419 }).category).toBe('permission')
  })

  it('5xx -> server', () => {
    expect(classifyError({ status: 500 }).category).toBe('server')
    expect(classifyError({ status: 503 }).category).toBe('server')
  })

  it('other 4xx / no signal -> unknown', () => {
    expect(classifyError({ status: 404 }).category).toBe('unknown')
    expect(classifyError({}).category).toBe('unknown')
  })

  it('parses trailing "HTTP <code>" from a thrown message', () => {
    expect(classifyError(new Error('request failed HTTP 502')).category).toBe('server')
  })

  it('never interpolates raw text into title/message; detail is sanitized', () => {
    const c = classifyError({ status: 500, error: 'boom\x00\x01<script>' })
    expect(c.title).toBe('服务器出错了') // fixed template, not raw text
    expect(c.detail).not.toContain('\x00')
  })

  it('surfaces structured per-row errors from a problem+json payload', () => {
    // Mirror an ApiError: the server body (with `errors`) lives on `.payload`.
    const apiError = {
      name: 'ApiError',
      message: 'validation failed: 2 errors (0 passed, 1 failed)',
      status: 422,
      payload: {
        type: 'https://backlink-publisher/problems/input-validation-error',
        title: 'Pipeline invocation failed',
        status: 422,
        detail: 'validation failed: 2 errors (0 passed, 1 failed)',
        error_class: 'InputValidationError',
        errors: [
          { detail: 'row 1: missing required output field \'target_url\'' },
          { detail: 'row 1: link count 3 is not between 6 and 8' },
        ],
      },
    }
    const c = classifyError(apiError)
    expect(c.errors).toEqual([
      "row 1: missing required output field 'target_url'",
      'row 1: link count 3 is not between 6 and 8',
    ])
  })

  it('leaves errors undefined when the server sends none', () => {
    const c = classifyError({ status: 500, error: 'boom' })
    expect(c.errors).toBeUndefined()
  })
})
