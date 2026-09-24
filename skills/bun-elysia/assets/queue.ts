import { env } from '@acme/config'
import { PgBoss } from 'pg-boss'

// One Postgres-backed queue (SKIP LOCKED). No Redis. Retries, cron, DLQ built in.
export const queue = new PgBoss({ connectionString: env.DATABASE_URL, schema: 'pgboss' })
queue.on('error', (error) => console.error('[queue]', error))
