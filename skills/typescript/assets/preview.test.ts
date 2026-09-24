import { HttpResponse, http } from 'msw'
import { setupServer } from 'msw/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { fetchPreview, UpstreamError } from './preview.ts'

const BASE = 'https://preview.test'
const server = setupServer()

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('fetchPreview', () => {
  it('validates and returns the preview', async () => {
    server.use(http.get(`${BASE}/v1/preview`, () => HttpResponse.json({ title: 'Docs', description: null })))
    await expect(fetchPreview(BASE, 'https://example.com')).resolves.toEqual({
      title: 'Docs',
      description: null,
    })
  })

  it('retries 5xx and then succeeds', async () => {
    let calls = 0
    server.use(
      http.get(`${BASE}/v1/preview`, () => {
        calls++
        return calls < 2
          ? new HttpResponse(null, { status: 503 })
          : HttpResponse.json({ title: 'ok', description: 'd' })
      }),
    )
    await expect(fetchPreview(BASE, 'https://example.com')).resolves.toMatchObject({ title: 'ok' })
    expect(calls).toBe(2)
  })

  it('does not retry 4xx', async () => {
    let calls = 0
    server.use(
      http.get(`${BASE}/v1/preview`, () => {
        calls++
        return new HttpResponse(null, { status: 404 })
      }),
    )
    await expect(fetchPreview(BASE, 'https://example.com')).rejects.toBeInstanceOf(UpstreamError)
    expect(calls).toBe(1)
  })

  it('rejects bodies that fail validation', async () => {
    server.use(http.get(`${BASE}/v1/preview`, () => HttpResponse.json({ title: 42 })))
    await expect(fetchPreview(BASE, 'https://example.com')).rejects.toThrow()
  })

  it('honours the caller signal', async () => {
    server.use(http.get(`${BASE}/v1/preview`, () => HttpResponse.json({ title: 't', description: null })))
    await expect(fetchPreview(BASE, 'https://example.com', AbortSignal.abort())).rejects.toMatchObject({
      name: 'AbortError',
    })
  })
})
