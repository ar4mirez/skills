import { queue } from '../../shared/queue'
import * as BillingService from './service'

export const BillingJobs = {
  sendInvoice: 'billing.send-invoice',
} as const

type SendInvoice = { accountId: string; invoiceId: string }

/** Called from services: enqueue after the domain write succeeds. */
export const enqueueSendInvoice = (data: SendInvoice) =>
  queue.send(BillingJobs.sendInvoice, data, {
    retryLimit: 5,
    retryBackoff: true,
    singletonKey: data.invoiceId,
  })

/** Registered by src/worker.ts only. Handlers are idempotent: jobs can run twice. */
export async function registerBillingWorkers() {
  await queue.createQueue(BillingJobs.sendInvoice)
  await queue.work<SendInvoice>(BillingJobs.sendInvoice, async ([job]) => {
    if (!job) return
    const invoice = await BillingService.findInvoice(job.data.accountId, job.data.invoiceId)
    if (invoice.status !== 'draft') return // already sent: idempotent no-op
    // ...deliver via the communications module's public API
  })
  await queue.schedule('billing.nightly-overdue', '0 3 * * *', {}, { tz: 'UTC' })
}
