import { Elysia } from 'elysia'
import { swagger } from '@elysiajs/swagger'
import { billing } from './modules/billing'

const app = new Elysia()
app.use(swagger())
app.use(billing)
app.listen(process.env.PORT || 3000)

export type App = typeof app
export { app }
