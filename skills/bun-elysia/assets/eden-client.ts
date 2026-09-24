import type { App } from '@acme/api' // type-only: no server code ships to the client
import { treaty } from '@elysia/eden'

export const api = treaty<App>(process.env.NEXT_PUBLIC_API_URL ?? 'localhost:3000', {
  fetch: { credentials: 'include' },
})

export async function getInvoice(id: string) {
  const { data, error } = await api.billing.invoices({ id }).get()
  if (error) {
    switch (error.status) {
      case 401:
        throw new Error('Sign in again')
      default:
        throw new Error(`Failed to load invoice (${error.status})`)
    }
  }
  return data // fully typed: { id, number, status, totalCents }
}
