// Second process from the same codebase (Kamal role `worker`): `bun src/worker.ts` or the compiled binary with WORKER=1.
import { registerBillingWorkers } from './modules/billing/public'
import { queue } from './shared/queue'

await queue.start()
await registerBillingWorkers()
console.log('worker started')

const shutdown = async () => {
  await queue.stop({ graceful: true, timeout: 25_000 }) // worker role isn't proxied: Kamal stops it with drain_timeout (30s default)
  process.exit(0)
}
process.on('SIGTERM', shutdown)
process.on('SIGINT', shutdown)
