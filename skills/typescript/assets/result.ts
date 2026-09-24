/** Expected outcomes are values; exceptions are for bugs and infrastructure failures. */
export type Result<T, E extends string = string> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E }

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value })
export const err = <E extends string>(error: E): Result<never, E> => ({ ok: false, error })

/** Compile-time exhaustiveness check for switch statements over unions. */
export function assertNever(value: never): never {
  throw new Error(`unhandled case: ${JSON.stringify(value)}`)
}
