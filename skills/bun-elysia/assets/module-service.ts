// Framework-blind: no Elysia imports. Plain functions, plain inputs; returns Results or throws DomainErrors.
// Import as a namespace: `import * as BillingService from './service'`.
import { db, schema } from '@acme/db'
import { and, eq } from 'drizzle-orm'
import { NotFoundError } from '../../shared/errors'
import { fail, ok, type Result } from '../../shared/result'
import type { BillingModel } from './model'

type Invoice = BillingModel['invoice']

const invoiceColumns = {
  id: schema.invoices.id,
  number: schema.invoices.number,
  status: schema.invoices.status,
  totalCents: schema.invoices.totalCents,
}

export async function findInvoice(accountId: string, id: string): Promise<Invoice> {
  const [invoice] = await db
    .select(invoiceColumns)
    .from(schema.invoices)
    .where(and(eq(schema.invoices.accountId, accountId), eq(schema.invoices.id, id)))
    .limit(1)
  if (!invoice) throw new NotFoundError('Invoice')
  return invoice
}

export async function createInvoice(
  accountId: string,
  input: BillingModel['createInvoiceBody'],
): Promise<Result<Invoice, 'duplicate_number'>> {
  const [invoice] = await db
    .insert(schema.invoices)
    .values({ accountId, ...input })
    .onConflictDoNothing({ target: [schema.invoices.accountId, schema.invoices.number] })
    .returning(invoiceColumns)
  return invoice ? ok(invoice) : fail('duplicate_number', `Invoice ${input.number} already exists`)
}
