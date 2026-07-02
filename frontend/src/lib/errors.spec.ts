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
})
