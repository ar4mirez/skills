import { Elysia } from 'elysia'
import { auth } from '../../plugins/auth'
import { BillingModel } from './model'
import * as BillingService from './service'

// 1 Elysia instance = 1 controller. Always method-chain; always destructure.
export const billing = new Elysia({ name: 'module.billing', prefix: '/billing' })
  .use(auth)
  .get('/invoices/:id', ({ params, account }) => BillingService.findInvoice(account.id, params.id), {
    auth: true,
    params: BillingModel.invoiceParams,
    response: { 200: BillingModel.invoice },
  })
  .post(
    '/invoices',
    async ({ body, account, status }) => {
      const result = await BillingService.createInvoice(account.id, body)
      if (!result.ok) return status(409, { error: result.error, message: result.message })
      return status(201, result.value)
    },
    {
      auth: true,
      body: BillingModel.createInvoiceBody,
      response: { 201: BillingModel.invoice, 409: BillingModel.problem },
    },
  )
