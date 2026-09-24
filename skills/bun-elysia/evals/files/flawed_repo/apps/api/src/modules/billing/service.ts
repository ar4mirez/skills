import { status } from 'elysia'

export class BillingService {
  static async checkout(cart: any) {
    if (!cart.items?.length) throw status(400, 'Empty cart')
    const res = await fetch(process.env.STRIPE_URL + '/checkout', { method: 'POST', body: JSON.stringify(cart) })
    return (await res.json()) as any
  }
}
