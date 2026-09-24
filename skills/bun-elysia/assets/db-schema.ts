import { index, integer, pgEnum, pgTable, text, timestamp, uniqueIndex, uuid } from 'drizzle-orm/pg-core'

export const invoiceStatus = pgEnum('invoice_status', ['draft', 'sent', 'paid', 'void'])

export const invoices = pgTable(
  'billing_invoices',
  {
    id: uuid('id').primaryKey().defaultRandom(),
    accountId: uuid('account_id').notNull(),
    number: text('number').notNull(),
    status: invoiceStatus('status').notNull().default('draft'),
    totalCents: integer('total_cents').notNull().default(0),
    createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    uniqueIndex('billing_invoices_account_number_idx').on(t.accountId, t.number),
    index('billing_invoices_account_status_idx').on(t.accountId, t.status),
  ],
)

export type Invoice = typeof invoices.$inferSelect
export type NewInvoice = typeof invoices.$inferInsert
