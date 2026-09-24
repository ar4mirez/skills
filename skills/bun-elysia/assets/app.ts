import { env } from '@acme/config'
import { openapi } from '@elysia/openapi'
import { Elysia } from 'elysia'
import { billing } from './modules/billing'

export const app = new Elysia()
  .use(openapi({ enabled: env.NODE_ENV !== 'production' }))
  .get('/up', () => 'ok') // kamal-proxy health check
  .use(billing)

export type App = typeof app
