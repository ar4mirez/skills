import { env } from '@acme/config'
import { db } from '@acme/db'
import { betterAuth } from 'better-auth'
import { drizzleAdapter } from 'better-auth/adapters/drizzle'
import { Elysia } from 'elysia'

export const authServer = betterAuth({
  database: drizzleAdapter(db, { provider: 'pg' }),
  basePath: '/api',
  secret: env.BETTER_AUTH_SECRET,
  emailAndPassword: { enabled: true },
  trustedOrigins: [env.WEB_URL],
})

// Named plugin = deduplicated singleton. `auth: true` on a route resolves { user, session, account } or 401s.
export const auth = new Elysia({ name: 'plugin.auth' }).mount('/auth', authServer.handler).macro({
  auth: {
    async resolve({ status, request: { headers } }) {
      const session = await authServer.api.getSession({ headers })
      if (!session) return status(401, 'Unauthorized')
      // Tenant resolution: replace with your account/organization lookup.
      return { user: session.user, session: session.session, account: { id: session.user.id } }
    },
  },
})
