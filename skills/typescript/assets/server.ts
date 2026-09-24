import { serve } from '@hono/node-server'
import { pino } from 'pino'
import { createApp } from './app.ts'
import { loadEnv } from './env.ts'
import { memoryStore } from './links.ts'

const env = loadEnv()
const logger = pino({ level: env.LOG_LEVEL })
const app = createApp({ store: memoryStore(), logger })

const server = serve({ fetch: app.fetch, port: env.PORT }, (info) => {
  logger.info({ port: info.port }, 'listening')
})

// kamal-proxy drains in-flight requests before SIGTERM; Docker kills after 10s.
function shutdown(signal: NodeJS.Signals): void {
  logger.info({ signal }, 'shutting down')
  const force = setTimeout(() => {
    logger.error('shutdown timed out')
    process.exit(1)
  }, 8_000)
  force.unref()
  server.close((error) => {
    if (error) logger.error({ err: error }, 'close failed')
    process.exitCode = error ? 1 : 0
  })
}

process.once('SIGTERM', shutdown)
process.once('SIGINT', shutdown)
