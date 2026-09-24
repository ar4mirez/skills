import { pino } from 'pino'
import { describe, expect, it } from 'vitest'
import { createApp } from './app.ts'
import { memoryStore } from './links.ts'

const setup = () => createApp({ store: memoryStore(), logger: pino({ level: 'silent' }) })

const post = (app: ReturnType<typeof setup>, body: unknown) =>
  app.request('/links', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })

describe('api', () => {
  it('serves the health check', async () => {
    const res = await setup().request('/up')
    expect(res.status).toBe(200)
    expect(await res.text()).toBe('ok')
  })

  it('creates a link and redirects to it', async () => {
    const app = setup()
    const created = await post(app, { code: 'docs', url: 'https://example.com/docs' })
    expect(created.status).toBe(201)
    expect(await created.json()).toEqual({ code: 'docs', url: 'https://example.com/docs' })

    const res = await app.request('/links/docs')
    expect(res.status).toBe(302)
    expect(res.headers.get('location')).toBe('https://example.com/docs')
  })

  it('rejects duplicate codes with 409', async () => {
    const app = setup()
    await post(app, { code: 'docs', url: 'https://example.com' })
    const res = await post(app, { code: 'docs', url: 'https://example.org' })
    expect(res.status).toBe(409)
  })

  it.each([
    [{ code: 'x', url: 'https://example.com' }],
    [{ code: 'docs', url: 'javascript:alert(1)' }],
    [{ code: 'docs', url: 'https://example.com', admin: true }],
  ])('rejects invalid bodies with 422: %j', async (body) => {
    const res = await post(setup(), body)
    expect(res.status).toBe(422)
  })

  it('returns 404 for unknown or malformed codes', async () => {
    const app = setup()
    expect((await app.request('/links/nope1')).status).toBe(404)
    expect((await app.request('/links/NOT_VALID')).status).toBe(404)
  })
})
