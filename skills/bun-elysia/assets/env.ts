import { type Static, Type as T } from '@sinclair/typebox'
import { Value } from '@sinclair/typebox/value'

const Env = T.Object({
  NODE_ENV: T.Union([T.Literal('development'), T.Literal('test'), T.Literal('production')], {
    default: 'development',
  }),
  PORT: T.Number({ default: 3000 }),
  DATABASE_URL: T.String({ minLength: 1 }),
  DATABASE_PREPARE: T.Boolean({ default: true }), // false behind PgBouncer transaction mode
  WEB_URL: T.String({ default: 'http://localhost:3001' }),
  BETTER_AUTH_SECRET: T.String({ minLength: 32, default: 'dev-only-secret-change-me-0123456789' }),
})

export type Env = Static<typeof Env>

/** Parse and validate process.env once at boot. Fails fast with every problem listed. */
export function loadEnv(source: Record<string, string | undefined> = process.env): Env {
  const converted = Value.Convert(Env, Value.Default(Env, { ...source }))
  const errors = [...Value.Errors(Env, converted)]
  if (errors.length > 0) {
    const list = errors.map((e) => `  ${e.path || '/'}: ${e.message}`).join('\n')
    throw new Error(`Invalid environment:\n${list}`)
  }
  return Value.Clean(Env, converted) as Env
}

export const env = loadEnv()
