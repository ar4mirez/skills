/**
 * Domain errors for exceptional paths. They carry an HTTP `status`, which Elysia
 * honours when they are thrown, so services never import Elysia.
 */
export class DomainError extends Error {
  readonly status: number = 500
}
export class NotFoundError extends DomainError {
  override readonly status = 404
  constructor(entity: string) {
    super(`${entity} not found`)
  }
}
export class ForbiddenError extends DomainError {
  override readonly status = 403
}
