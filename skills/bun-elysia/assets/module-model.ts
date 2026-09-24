import { t, type UnwrapSchema } from 'elysia'

// Single source of truth: runtime validation, TS types, OpenAPI, Eden.
export const BillingModel = {
  invoiceParams: t.Object({ id: t.String({ format: 'uuid' }) }),
  createInvoiceBody: t.Object({
    number: t.String({ minLength: 1, maxLength: 32 }),
    totalCents: t.Integer({ minimum: 0 }),
  }),
  invoice: t.Object({
    id: t.String(),
    number: t.String(),
    status: t.UnionEnum(['draft', 'sent', 'paid', 'void']),
    totalCents: t.Integer(),
  }),
  problem: t.Object({ error: t.String(), message: t.String() }),
} as const

export type BillingModel = { [K in keyof typeof BillingModel]: UnwrapSchema<(typeof BillingModel)[K]> }
