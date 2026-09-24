import { sValidator } from '@hono/standard-validator'
import { Hono } from 'hono'
import { HTTPException } from 'hono/http-exception'
import type { Logger } from 'pino'
import { CreateLink, createLink, LinkCode, type LinkStore } from './links.ts'
import { assertNever } from './result.ts'

export interface Deps {
  readonly store: LinkStore
  readonly logger: Logger
}

/** Builds the app without listening, so tests call `app.request()` directly. */
export function createApp({ store, logger }: Deps) {
  const app = new Hono()

  app.onError((error, c) => {
    if (error instanceof HTTPException) return error.getResponse()
    logger.error({ err: error, path: c.req.path }, 'unhandled error')
    return c.json({ error: 'internal_error' }, 500)
  })

  return app
    .get('/up', (c) => c.text('ok'))
    .post(
      '/links',
      sValidator('json', CreateLink, (result, c) => {
        if (!result.success) return c.json({ error: 'invalid_body', issues: result.error }, 422)
      }),
      async (c) => {
        const result = await createLink(store, c.req.valid('json'))
        if (result.ok) return c.json({ code: result.value.code, url: result.value.url }, 201)
        switch (result.error) {
          case 'code_taken':
            return c.json({ error: result.error }, 409)
          default:
            return assertNever(result.error)
        }
      },
    )
    .get('/links/:code', async (c) => {
      const code = LinkCode.safeParse(c.req.param('code'))
      if (!code.success) return c.json({ error: 'not_found' }, 404)
      const link = await store.get(code.data)
      return link ? c.redirect(link.url, 302) : c.json({ error: 'not_found' }, 404)
    })
}

export type App = ReturnType<typeof createApp>
