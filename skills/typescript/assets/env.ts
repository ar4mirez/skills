import * as z from 'zod'

const EnvSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().int().min(1).max(65_535).default(3000),
  LOG_LEVEL: z.enum(['fatal', 'error', 'warn', 'info', 'debug', 'trace']).default('info'),
  PREVIEW_BASE_URL: z.url().default('https://preview.example.com'),
})

export type Env = z.infer<typeof EnvSchema>

/** Parses the environment once at boot; a bad value stops the process with every issue listed. */
export function loadEnv(source: Record<string, string | undefined> = process.env): Env {
  const parsed = EnvSchema.safeParse(source)
  if (!parsed.success) {
    throw new Error(`invalid environment:\n${z.prettifyError(parsed.error)}`)
  }
  return parsed.data
}
