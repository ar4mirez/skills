#!/usr/bin/env bun
/**
 * Scaffold an Elysia domain module in the house shape:
 *   index.ts (controller) · model.ts (schemas) · service.ts (framework-blind) · public.ts · <name>.test.ts
 *
 * Usage:
 *   bun scripts/new-module.ts <name> [--dir apps/api/src/modules] [--force] [--dry-run]
 *
 * <name> is kebab-case (e.g. `billing`, `team-invites`). Nothing is overwritten unless --force.
 * After scaffolding: register the controller in app.ts with `.use(<camelName>)`.
 * Exit codes: 0 = created (or dry run), 1 = target exists, 2 = bad input.
 */
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

function usage(code: number): never {
  const text =
    'Usage: bun scripts/new-module.ts <name> [--dir apps/api/src/modules] [--force] [--dry-run]\n\n' +
    'Scaffold an Elysia module (controller, model, framework-blind service, public API, test).\n' +
    'Example:\n  bun scripts/new-module.ts team-invites --dir apps/api/src/modules\n'
  ;(code === 0 ? console.log : console.error)(text)
  process.exit(code)
}

const args = process.argv.slice(2)
if (args.includes('-h') || args.includes('--help')) usage(0)
const force = args.includes('--force')
const dryRun = args.includes('--dry-run')
const dirIndex = args.indexOf('--dir')
const baseDir = dirIndex >= 0 ? args[dirIndex + 1] : 'apps/api/src/modules'
const name = args.find((a, i) => !a.startsWith('-') && (dirIndex < 0 || i !== dirIndex + 1))

if (!name || !baseDir) usage(2)
if (!/^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.test(name)) {
  console.error(`Error: '${name}' must be kebab-case (lowercase letters, digits, single hyphens), e.g. team-invites.`)
  process.exit(2)
}

const camel = name.replace(/-([a-z0-9])/g, (_, c: string) => c.toUpperCase())
const pascal = camel[0]?.toUpperCase() + camel.slice(1)
const target = resolve(baseDir, name)

const files: Record<string, string> = {
  'model.ts': `import { t, type UnwrapSchema } from 'elysia'

// Single source of truth: runtime validation, TS types, OpenAPI, and Eden client types.
export const ${pascal}Model = {
  params: t.Object({ id: t.String({ format: 'uuid' }) }),
  createBody: t.Object({ name: t.String({ minLength: 1, maxLength: 120 }) }),
  item: t.Object({ id: t.String(), name: t.String() }),
  problem: t.Object({ error: t.String(), message: t.String() }),
} as const

export type ${pascal}Model = { [K in keyof typeof ${pascal}Model]: UnwrapSchema<(typeof ${pascal}Model)[K]> }
`,
  'service.ts': `// Framework-blind: no Elysia imports. Plain functions; return Results or throw DomainErrors.
// Import as a namespace: \`import * as ${pascal}Service from './service'\`.
import { NotFoundError } from '../../shared/errors'
import { fail, ok, type Result } from '../../shared/result'
import type { ${pascal}Model } from './model'

type Item = ${pascal}Model['item']

export async function find(accountId: string, id: string): Promise<Item> {
  // TODO: query with Drizzle, always scoped by accountId.
  void accountId
  throw new NotFoundError(\`${pascal} \${id}\`)
}

export async function create(accountId: string, input: ${pascal}Model['createBody']): Promise<Result<Item, 'conflict'>> {
  // TODO: insert with Drizzle inside a transaction; enqueue side effects after the write.
  void accountId
  return input.name ? ok({ id: crypto.randomUUID(), name: input.name }) : fail('conflict', 'Name is taken')
}
`,
  'public.ts': `// The ONLY file other modules (and entrypoints) may import from ${name}. Keep it small.
export type { ${pascal}Model } from './model'
export { create, find } from './service'
`,
  'index.ts': `import { Elysia } from 'elysia'
import { auth } from '../../plugins/auth'
import { ${pascal}Model } from './model'
import * as ${pascal}Service from './service'

// 1 Elysia instance = 1 controller. Always method-chain; always destructure.
export const ${camel} = new Elysia({ name: 'module.${name}', prefix: '/${name}' })
  .use(auth)
  .get('/:id', ({ params, account }) => ${pascal}Service.find(account.id, params.id), {
    auth: true,
    params: ${pascal}Model.params,
    response: { 200: ${pascal}Model.item },
  })
  .post(
    '/',
    async ({ body, account, status }) => {
      const result = await ${pascal}Service.create(account.id, body)
      if (!result.ok) return status(409, { error: result.error, message: result.message })
      return status(201, result.value)
    },
    {
      auth: true,
      body: ${pascal}Model.createBody,
      response: { 201: ${pascal}Model.item, 409: ${pascal}Model.problem },
    },
  )
`,
  [`${name}.test.ts`]: `import { describe, expect, it } from 'bun:test'
import { treaty } from '@elysia/eden'
import { Elysia } from 'elysia'
import { ${camel} } from '.'

const api = treaty(new Elysia().use(${camel}))
const headers = { 'x-account-id': 'acct_test' }

describe('${name}', () => {
  it('requires authentication', async () => {
    const { status } = await api['${name}'].post({ name: 'x' })
    expect(status).toBe(401)
  })

  it('creates', async () => {
    const { data, status } = await api['${name}'].post({ name: 'First' }, { headers })
    expect(status).toBe(201)
    expect(data?.name).toBe('First')
  })

  it('rejects an invalid body with 422', async () => {
    const { status } = await api['${name}'].post({ name: '' }, { headers })
    expect(status).toBe(422)
  })
})
`,
}

if (existsSync(target) && !force) {
  console.error(`Error: ${target} already exists. Pass --force to overwrite.`)
  process.exit(1)
}

for (const [file, content] of Object.entries(files)) {
  const path = join(target, file)
  if (dryRun) {
    console.log(`would write ${path}`)
    continue
  }
  mkdirSync(target, { recursive: true })
  writeFileSync(path, content)
  console.log(`wrote ${path}`)
}
if (!dryRun)
  console.log(
    `\nNext: add \`.use(${camel})\` in app.ts (import { ${camel} } from './modules/${name}'), then replace the TODOs.\n` +
      'Expects ../../shared/{errors,result}.ts and ../../plugins/auth.ts (see assets/).',
  )
