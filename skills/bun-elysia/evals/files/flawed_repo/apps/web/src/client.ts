import { treaty } from '@elysiajs/eden'
import { app } from '@shop/api'

export const api = treaty<typeof app>(process.env.NEXT_PUBLIC_API_URL ?? 'localhost:3000')
