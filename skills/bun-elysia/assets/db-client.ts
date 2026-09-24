import { env } from '@acme/config'
import { SQL } from 'bun'
import { drizzle } from 'drizzle-orm/bun-sql'
import * as schema from './schema'

const client = new SQL({ url: env.DATABASE_URL, max: 10, prepare: env.DATABASE_PREPARE })

export const db = drizzle({ client, schema, casing: 'snake_case' })
export type Db = typeof db
export type Tx = Parameters<Parameters<Db['transaction']>[0]>[0]
export { schema }
