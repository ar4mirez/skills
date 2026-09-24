/** The only result type for expected outcomes. Unexpected failures throw. */
export type Result<T, E extends string = string> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: E; readonly message: string }

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value })
export const fail = <E extends string>(error: E, message: string): Result<never, E> => ({
  ok: false,
  error,
  message,
})
