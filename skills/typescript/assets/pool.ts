/**
 * Maps `items` through `fn` with at most `limit` calls in flight, preserving
 * order. The first rejection aborts the shared signal so siblings stop early.
 */
export async function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, signal: AbortSignal) => Promise<R>,
): Promise<R[]> {
  if (!Number.isInteger(limit) || limit < 1) throw new RangeError(`limit must be >= 1, got ${limit}`)
  const controller = new AbortController()
  const results = new Array<R>(items.length)
  let next = 0
  const worker = async (): Promise<void> => {
    while (next < items.length && !controller.signal.aborted) {
      const index = next++
      try {
        results[index] = await fn(items[index] as T, controller.signal)
      } catch (error) {
        controller.abort(error)
        throw error
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}
