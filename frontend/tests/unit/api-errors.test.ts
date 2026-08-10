import { describe, expect, it } from 'vitest'
import { createApiError, isApiError, toUserMessage } from '@/api/errors'

describe('api errors', () => {
  it('maps status codes', () => {
    expect(createApiError({ status: 401 }).code).toBe('unauthorized')
    expect(createApiError({ status: 403 }).code).toBe('forbidden')
    expect(createApiError({ status: 409 }).code).toBe('conflict')
    expect(createApiError({ status: 422 }).code).toBe('validation')
    expect(createApiError({ status: 429 }).code).toBe('rate_limited')
    expect(createApiError({ status: 500 }).code).toBe('server')
  })

  it('hides sql/driver details from user message', () => {
    const err = createApiError({
      status: 500,
      detail: 'ORA-12609: TNS: receive timeout',
    })
    expect(err.message).not.toMatch(/ORA-12609/i)
    expect(err.message).toContain('服务处理失败')
  })

  it('toUserMessage and type guard', () => {
    const err = createApiError({ status: 403, message: '无权限' })
    expect(isApiError(err)).toBe(true)
    expect(toUserMessage(err)).toBe('无权限')
    expect(toUserMessage(new Error('x'), 'fallback')).toBe('x')
  })
})
