import { defineConfig } from 'drizzle-kit'

export default defineConfig({
  dialect: 'postgresql',
  schema: './src/schema/index.ts',
  out: './migrations',
  dbCredentials: { url: process.env.DATABASE_DIRECT_URL ?? process.env.DATABASE_URL ?? '' },
  strict: true,
})
