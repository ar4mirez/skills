/** Options for {@link retry}. Every field is optional; defaults suit network calls. */
export interface RetryOptions {
  /** Total attempts including the first one. Default 3. */
  readonly attempts?: number
  /** Delay before the second attempt, doubled each time. Default 100 ms. */
  readonly baseDelayMs?: number
  /** Upper bound for a single delay. Default 5 000 ms. */
  readonly maxDelayMs?: number
  /** Aborts the pending attempt and any backoff sleep. */
  readonly signal?: AbortSignal
  /** Return false for errors that retrying cannot fix (4xx, validation). Default: retry everything. */
  readonly shouldRetry?: (error: unknown, attempt: number) => boolean
  /** Source of randomness for jitter; inject a constant in tests. Default Math.random. */
  readonly random?: () => number
}

/** Thrown when every attempt failed. `cause` holds the last error. */
export class RetryError extends Error {
  override readonly name = 'RetryError'
  readonly attempts: number

  constructor(attempts: number, cause: unknown) {
    super(`gave up after ${attempts} attempt(s)`, { cause })
    this.attempts = attempts
  }
}

/** Resolves after `ms`, or rejects with the signal's reason when it aborts first. */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted()
    const onAbort = (): void => {
      clearTimeout(timer)
      reject(signal?.reason)
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * Runs `fn` until it resolves, retrying with full-jitter exponential backoff.
 * `fn` receives the attempt number (1-based) and the caller's signal so it can
 * pass it to `fetch` or a driver. Aborts and errors rejected by `shouldRetry`
 * are rethrown unchanged; exhausting every attempt throws a {@link RetryError}.
 */
export async function retry<T>(
  fn: (attempt: number, signal: AbortSignal | undefined) => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const {
    attempts = 3,
    baseDelayMs = 100,
    maxDelayMs = 5_000,
    signal,
    shouldRetry = () => true,
    random = Math.random,
  } = options
  if (!Number.isInteger(attempts) || attempts < 1) {
    throw new RangeError(`attempts must be a positive integer, got ${attempts}`)
  }

  let lastError: unknown
  for (let attempt = 1; attempt <= attempts; attempt++) {
    if (attempt > 1) {
      const ceiling = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 2))
      await sleep(Math.floor(random() * ceiling), signal)
    }
    signal?.throwIfAborted()
    try {
      return await fn(attempt, signal)
    } catch (error) {
      // Aborts and permanent failures surface unchanged so callers can branch on them.
      if (signal?.aborted || !shouldRetry(error, attempt)) throw error
      lastError = error
    }
  }
  throw new RetryError(attempts, lastError)
}
