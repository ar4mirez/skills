import * as z from 'zod'
import { err, ok, type Result } from './result.ts'

/** Branded so a raw string can't be passed where a validated code is required. */
export const LinkCode = z
  .string()
  .regex(/^[a-z0-9]{4,32}$/, 'use 4-32 lowercase letters or digits')
  .brand<'LinkCode'>()
export type LinkCode = z.infer<typeof LinkCode>

export const CreateLink = z.strictObject({
  code: LinkCode,
  url: z.url({ protocol: /^https?$/ }),
})
export type CreateLink = z.infer<typeof CreateLink>

export interface Link {
  readonly code: LinkCode
  readonly url: string
  readonly createdAt: Date
}

/** The consumer owns the port; tests pass the in-memory implementation. */
export interface LinkStore {
  get(code: LinkCode): Promise<Link | undefined>
  insert(link: Link): Promise<boolean>
}

export type CreateError = 'code_taken'

export async function createLink(
  store: LinkStore,
  input: CreateLink,
  now: () => Date = () => new Date(),
): Promise<Result<Link, CreateError>> {
  const link: Link = { code: input.code, url: input.url, createdAt: now() }
  return (await store.insert(link)) ? ok(link) : err('code_taken')
}

export function memoryStore(): LinkStore {
  const links = new Map<LinkCode, Link>()
  return {
    get: async (code) => links.get(code),
    insert: async (link) => {
      if (links.has(link.code)) return false
      links.set(link.code, link)
      return true
    },
  }
}
