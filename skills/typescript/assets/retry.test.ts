import { describe, expect, expectTypeOf, it, vi } from 'vitest'
import { RetryError, retry, sleep } from './index.ts'

const noJitter = { baseDelayMs: 1, random: () => 0 }

describe('retry', () => {
  it('returns the first successful result', async () => {
    const fn = vi.fn(async (attempt: number) => {
      if (attempt < 3) throw new Error(`boom ${attempt}`)
      return 'ok'
    })
    await expect(retry(fn, noJitter)).resolves.toBe('ok')
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it('wraps the last error in RetryError when attempts run out', async () => {
    const last = new Error('still down')
    const error = await retry(() => Promise.reject(last), { ...noJitter, attempts: 2 }).catch(
      (e: unknown) => e,
    )
    expect(error).toBeInstanceOf(RetryError)
    expect(error).toMatchObject({ attempts: 2, cause: last })
  })

  it('rethrows permanent errors without retrying', async () => {
    const fn = vi.fn(() => Promise.reject(new TypeError('bad input')))
    await expect(retry(fn, { ...noJitter, shouldRetry: (e) => !(e instanceof TypeError) })).rejects.toThrow(
      TypeError,
    )
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('stops when the signal aborts during backoff', async () => {
    const controller = new AbortController()
    const fn = vi.fn(() => {
      controller.abort(new Error('shutdown'))
      return Promise.reject(new Error('transient'))
    })
    await expect(retry(fn, { signal: controller.signal, baseDelayMs: 10_000 })).rejects.toThrow('transient')
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('rejects invalid attempts', async () => {
    await expect(retry(() => Promise.resolve(1), { attempts: 0 })).rejects.toThrow(RangeError)
  })

  it('infers the result type from fn', () => {
    expectTypeOf(retry(() => Promise.resolve(42))).toEqualTypeOf<Promise<number>>()
    expectTypeOf<RetryError['attempts']>().toBeNumber()
  })
})

describe('sleep', () => {
  it('rejects with the abort reason', async () => {
    await expect(sleep(10_000, AbortSignal.timeout(5))).rejects.toMatchObject({ name: 'TimeoutError' })
  })
})
