import { describe, expect, it, mock } from 'bun:test'
import { treaty } from '@elysia/eden'

const invoice = {
  id: '5f9d4c3a-1b2c-4d5e-8f90-123456789abc',
  number: 'INV-1',
  status: 'draft' as const,
  totalCents: 1000,
}
mock.module('./service', () => ({
  findInvoice: async () => invoice,
  createInvoice: async (_: string, input: { number: string }) =>
    input.number === 'DUP'
      ? { ok: false, error: 'duplicate_number', message: 'Invoice DUP already exists' }
      : { ok: true, value: { ...invoice, number: input.number } },
}))

const { app } = await import('../../app')
const api = treaty(app)
const headers = { 'x-account-id': 'acct_1' }

describe('billing', () => {
  it('requires authentication', async () => {
    const { status } = await api.billing.invoices({ id: invoice.id }).get()
    expect(status).toBe(401)
  })

  it('creates an invoice', async () => {
    const { data, status } = await api.billing.invoices.post(
      { number: 'INV-2', totalCents: 500 },
      { headers },
    )
    expect(status).toBe(201)
    expect(data?.number).toBe('INV-2')
  })

  it('returns 409 for a duplicate number', async () => {
    const { error } = await api.billing.invoices.post({ number: 'DUP', totalCents: 500 }, { headers })
    expect(error?.status).toBe(409)
  })

  it('rejects invalid bodies with 422', async () => {
    const { status } = await api.billing.invoices.post({ number: 'INV-3', totalCents: -1 }, { headers }) // minimum is runtime-only
    expect(status).toBe(422)
  })
})
