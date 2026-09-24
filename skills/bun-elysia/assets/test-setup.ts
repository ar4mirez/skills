// Preloaded by bunfig.toml [test].preload. Swaps real auth for a header-based stub in tests only.
import { mock } from 'bun:test'
import { Elysia } from 'elysia'

process.env.DATABASE_URL ??= 'postgres://localhost:5432/acme_test'

const testAuth = new Elysia({ name: 'plugin.auth' }).macro({
  auth: {
    resolve({ headers, status }) {
      const accountId = headers['x-account-id']
      if (!accountId) return status(401, 'Unauthorized')
      const user = { id: accountId, email: `${accountId}@test.local`, name: 'Test User' }
      return { user, session: { id: `sess_${accountId}` }, account: { id: accountId } }
    },
  },
})

mock.module('../src/plugins/auth', () => ({ auth: testAuth }))
