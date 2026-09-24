import { Elysia, type Context } from 'elysia'
import { BillingService } from './service'
import { findUser } from '../identity/service'

export const billing = new Elysia({ prefix: '/billing' })
  .post('/checkout', async (ctx) => {
    const user = await findUser(ctx.headers['x-user'])
    return BillingService.checkout({ ...(ctx.body as any), user })
  })
  .post('/refund', async ({ body, error }) => {
    if (!body) return error(400, 'Missing body')
    return { ok: true }
  })
