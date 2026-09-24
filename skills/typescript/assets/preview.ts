import { retry } from '@acme/retry'
import * as z from 'zod'

const Preview = z.object({ title: z.string(), description: z.string().nullable() })
export type Preview = z.infer<typeof Preview>

export class UpstreamError extends Error {
  override readonly name = 'UpstreamError'
  readonly status: number

  constructor(status: number, options?: ErrorOptions) {
    super(`preview service answered ${status}`, options)
    this.status = status
  }
}

/**
 * Fetches link metadata from the preview service. Every call has a deadline
 * (the caller's signal combined with a per-attempt timeout), 5xx responses are
 * retried, and the body is validated before it's trusted.
 */
export async function fetchPreview(baseUrl: string, url: string, signal?: AbortSignal): Promise<Preview> {
  return retry(
    async () => {
      const deadline = AbortSignal.timeout(2_000)
      const res = await fetch(new URL(`/v1/preview?url=${encodeURIComponent(url)}`, baseUrl), {
        signal: signal ? AbortSignal.any([signal, deadline]) : deadline,
        headers: { accept: 'application/json' },
      })
      if (!res.ok) throw new UpstreamError(res.status)
      return Preview.parse(await res.json())
    },
    {
      attempts: 3,
      baseDelayMs: 50,
      ...(signal ? { signal } : {}),
      shouldRetry: (error) => error instanceof UpstreamError && error.status >= 500,
    },
  )
}
