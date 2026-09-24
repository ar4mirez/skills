#!/usr/bin/env bun
/**
 * Static health check of a Bun + Elysia (mono)repo. No install, no network.
 *
 * Usage:
 *   bun scripts/audit.ts [ROOT] [--json] [--fail-on high|medium|low|none]
 *
 * high    packages depending on apps; client apps importing server code at runtime (not `import type`);
 *         Elysia/Eden version drift between server and clients; tsconfig without `strict`;
 *         compiled binary on Alpine without a musl target
 * medium  services importing Elysia (not framework-blind); handlers taking the whole Context;
 *         non-chained Elysia instances; cross-module imports that bypass `public.ts`; module cycles;
 *         POST/PUT/PATCH routes without a `body` schema; dependency ranges drifting across
 *         workspaces (use `catalog:`); deprecated `lucia`; `--bytecode` without `--format=esm`;
 *         `bun check` (not a command); no lockfile
 * low     legacy `bun.lockb`; `@elysiajs/swagger`; deprecated `error()` helper; `process.env` outside
 *         the config module; `any`; runtime `.ts` in the final Docker stage; Redis queues when pg-boss
 *         would do; missing Biome config or ESLint/Prettier alongside Biome
 *
 * Exit codes: 0 = no findings at/above --fail-on (default: high), 1 = findings, 2 = bad input.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { basename, dirname, join, relative, resolve, sep } from 'node:path'

type Severity = 'high' | 'medium' | 'low'
type Finding = { severity: Severity; check: string; location: string; message: string }
type Workspace = { dir: string; name: string; pkg: Record<string, any> }

const SEVERITIES: Severity[] = ['high', 'medium', 'low']
const DEP_FIELDS = ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'] as const
const SKIP_DIRS = new Set(['node_modules', 'dist', 'build', '.next', '.expo', '.git', 'coverage', '.turbo', 'migrations'])

function usage(code: number): never {
  const text =
    'Usage: bun scripts/audit.ts [ROOT] [--json] [--fail-on high|medium|low|none]\n\n' +
    'Static health check of a Bun + Elysia monorepo (workspaces, boundaries, Elysia patterns, deploy).\n' +
    'Examples:\n  bun scripts/audit.ts .\n  bun scripts/audit.ts ~/code/acme --json --fail-on medium\n'
  ;(code === 0 ? console.log : console.error)(text)
  process.exit(code)
}

function readJson(file: string): Record<string, any> | null {
  try {
    return JSON.parse(readFileSync(file, 'utf8'))
  } catch {
    return null
  }
}

/** Parse JSON-with-comments (tsconfig) well enough for the keys we need. */
function readJsonc(file: string): Record<string, any> | null {
  try {
    const text = readFileSync(file, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/(^|[^:"'])\/\/.*$/gm, '$1')
      .replace(/,(\s*[}\]])/g, '$1')
    return JSON.parse(text)
  } catch {
    return null
  }
}

function walk(dir: string, exts: string[], out: string[] = []): string[] {
  if (!existsSync(dir)) return out
  for (const entry of readdirSync(dir)) {
    if (SKIP_DIRS.has(entry)) continue
    const full = join(dir, entry)
    const st = statSync(full)
    if (st.isDirectory()) walk(full, exts, out)
    else if (exts.some((e) => entry.endsWith(e)) && !entry.endsWith('.d.ts')) out.push(full)
  }
  return out
}

function expandWorkspaces(root: string, patterns: string[]): string[] {
  const dirs: string[] = []
  for (const pattern of patterns) {
    if (pattern.startsWith('!')) continue
    if (pattern.endsWith('/*') || pattern.endsWith('/**')) {
      const base = join(root, pattern.replace(/\/\*\*?$/, ''))
      if (!existsSync(base)) continue
      for (const entry of readdirSync(base)) {
        const full = join(base, entry)
        if (statSync(full).isDirectory() && existsSync(join(full, 'package.json'))) dirs.push(full)
      }
    } else if (existsSync(join(root, pattern, 'package.json'))) {
      dirs.push(join(root, pattern))
    }
  }
  return [...new Set(dirs)]
}

/** Return the source of each `.post(`/`.put(`/`.patch(` call (balanced parens, string-aware). */
function routeCalls(src: string, methods: string[]): { method: string; index: number; body: string }[] {
  const calls: { method: string; index: number; body: string }[] = []
  const re = new RegExp(`\\.(${methods.join('|')})\\(`, 'g')
  for (let m = re.exec(src); m; m = re.exec(src)) {
    let depth = 0
    let quote: string | null = null
    let i = m.index + m[0].length - 1
    for (; i < src.length; i++) {
      const ch = src[i]
      if (quote) {
        if (ch === '\\') i++
        else if (ch === quote) quote = null
        continue
      }
      if (ch === '"' || ch === "'" || ch === '`') quote = ch
      else if (ch === '(') depth++
      else if (ch === ')' && --depth === 0) break
    }
    calls.push({ method: m[1] ?? '', index: m.index, body: src.slice(m.index, i + 1) })
  }
  return calls
}

const lineOf = (src: string, index: number) => src.slice(0, index).split('\n').length

/** Each elementary cycle once, as [a, b, ..., a], starting at its smallest node. */
function findCycles(edges: Map<string, Set<string>>): string[][] {
  const cycles = new Map<string, string[]>()
  const visit = (start: string, node: string, path: string[]) => {
    for (const next of edges.get(node) ?? []) {
      if (next === start) {
        const cycle = [...path, start]
        const key = [...path].sort().join('|')
        if (path.every((n) => n >= start) && !cycles.has(key)) cycles.set(key, cycle)
      } else if (!path.includes(next) && next > start) visit(start, next, [...path, next])
    }
  }
  for (const start of edges.keys()) visit(start, start, [start])
  return [...cycles.values()]
}

class Auditor {
  readonly findings: Finding[] = []
  readonly facts: Record<string, unknown> = {}
  private workspaces: Workspace[] = []

  constructor(readonly root: string) {}

  private add(severity: Severity, check: string, location: string, message: string) {
    this.findings.push({ severity, check, location, message })
  }

  private rel(file: string) {
    return relative(this.root, file) || '.'
  }

  run() {
    const rootPkg = readJson(join(this.root, 'package.json'))
    if (!rootPkg) throw new Error(`no readable package.json in ${this.root}`)
    this.facts.bun = rootPkg.packageManager ?? rootPkg.engines?.bun ?? null
    this.checkLockfile()
    this.loadWorkspaces(rootPkg)
    this.checkDependencies(rootPkg)
    this.checkTsconfig()
    this.checkSources()
    this.checkDocker()
    this.checkTooling(rootPkg)
    return this
  }

  private checkLockfile() {
    const text = existsSync(join(this.root, 'bun.lock'))
    const binary = existsSync(join(this.root, 'bun.lockb'))
    if (binary && !text)
      this.add('low', 'binary-lockfile', 'bun.lockb', 'Legacy binary lockfile. Run `bun install --save-text-lockfile` and commit the reviewable bun.lock.')
    if (!text && !binary)
      this.add('medium', 'no-lockfile', '.', 'No bun.lock committed. Installs are not reproducible; run `bun install` and commit bun.lock.')
  }

  private loadWorkspaces(rootPkg: Record<string, any>) {
    const ws = rootPkg.workspaces
    const patterns: string[] = Array.isArray(ws) ? ws : (ws?.packages ?? [])
    const dirs = expandWorkspaces(this.root, patterns)
    this.workspaces = dirs.map((dir) => {
      const pkg = readJson(join(dir, 'package.json')) ?? {}
      return { dir, name: pkg.name ?? basename(dir), pkg }
    })
    if (!this.workspaces.length) this.workspaces = [{ dir: this.root, name: rootPkg.name ?? '.', pkg: rootPkg }]
    this.facts.workspaces = this.workspaces.map((w) => this.rel(w.dir))
  }

  private isApp(w: Workspace) {
    return this.rel(w.dir).split(sep)[0] === 'apps'
  }

  private isServer(w: Workspace) {
    const hasEden = (f: (typeof DEP_FIELDS)[number]) =>
      f !== 'devDependencies' && Object.keys(w.pkg[f] ?? {}).some((d) => d === '@elysia/eden' || d === '@elysiajs/eden')
    return DEP_FIELDS.some((f) => w.pkg[f]?.elysia) && !DEP_FIELDS.some(hasEden)
  }

  private checkDependencies(rootPkg: Record<string, any>) {
    const byName = new Map(this.workspaces.map((w) => [w.name, w]))
    const ranges = new Map<string, Map<string, string[]>>()

    for (const w of this.workspaces) {
      for (const field of DEP_FIELDS) {
        for (const [dep, range] of Object.entries<string>(w.pkg[field] ?? {})) {
          const target = byName.get(dep)
          if (target && target !== w) {
            if (!this.isApp(w) && this.isApp(target))
              this.add('high', 'package-depends-on-app', this.rel(join(w.dir, 'package.json')),
                `${w.name} depends on app ${dep}. Packages are shared foundations; they must never depend on apps.`)
            else if (this.isApp(w) && this.isApp(target) && !(field === 'devDependencies' && this.isServer(target)))
              this.add('medium', 'app-depends-on-app', this.rel(join(w.dir, 'package.json')),
                `${w.name} depends on app ${dep} via ${field}. Only a devDependency on the API (for Eden types) is allowed; move shared code to packages/.`)
            continue
          }
          if (!range.startsWith('workspace:') && !range.startsWith('catalog:')) {
            const m = ranges.get(dep) ?? new Map<string, string[]>()
            m.set(range, [...(m.get(range) ?? []), w.name])
            ranges.set(dep, m)
          }
          if (dep === 'lucia')
            this.add('medium', 'deprecated-lucia', this.rel(join(w.dir, 'package.json')), 'lucia is deprecated. Use Better Auth (mounted into Elysia, with an `auth` macro).')
          if (dep === '@elysiajs/swagger')
            this.add('low', 'swagger-plugin', this.rel(join(w.dir, 'package.json')), '@elysiajs/swagger is superseded by @elysia/openapi.')
          if (dep === 'bullmq' || dep === 'ioredis')
            this.add('low', 'redis-queue', this.rel(join(w.dir, 'package.json')), `${dep}: prefer pg-boss (Postgres SKIP LOCKED) unless Redis is already core infrastructure.`)
        }
      }
    }

    const catalog = { ...(rootPkg.catalog ?? {}), ...(rootPkg.workspaces?.catalog ?? {}) }
    for (const [dep, m] of ranges) {
      if (m.size < 2) continue
      const detail = [...m].map(([r, names]) => `${r} (${names.join(', ')})`).join(' vs ')
      const critical = dep === 'elysia' || dep.endsWith('/eden') || dep === '@sinclair/typebox'
      this.add(critical ? 'high' : 'medium', critical ? 'eden-version-drift' : 'version-drift', 'package.json',
        `${dep} has different ranges: ${detail}. ${catalog[dep] ? 'Use "catalog:"' : 'Add it to the root catalog and use "catalog:"'}` +
          (critical ? ' (Eden types break when server and client resolve different Elysia/TypeBox versions).' : '.'))
    }
  }

  private checkTsconfig() {
    const seen = new Set<string>()
    const strictOf = (file: string, depth = 0): boolean | undefined => {
      if (depth > 5 || !existsSync(file)) return undefined
      const cfg = readJsonc(file)
      if (!cfg) return undefined
      if (cfg.compilerOptions?.strict !== undefined) return cfg.compilerOptions.strict
      const ext = Array.isArray(cfg.extends) ? cfg.extends[0] : cfg.extends
      if (typeof ext === 'string' && ext.startsWith('.')) return strictOf(resolve(dirname(file), ext.endsWith('.json') ? ext : `${ext}.json`), depth + 1)
      return undefined
    }
    for (const w of this.workspaces) {
      const file = join(w.dir, 'tsconfig.json')
      if (!existsSync(file) || seen.has(file)) continue
      seen.add(file)
      if (strictOf(file) !== true)
        this.add('high', 'tsconfig-not-strict', this.rel(file), 'strict is not enabled. Elysia inference and Eden end-to-end types require "strict": true.')
    }
  }

  private checkSources() {
    const serverNames = this.workspaces.filter((w) => this.isServer(w)).map((w) => w.name)
    let anyCount = 0
    let anyFile = ''
    const moduleEdges = new Map<string, Set<string>>()
    for (const w of this.workspaces) {
      const files = walk(join(w.dir, 'src'), ['.ts', '.tsx'])
      for (const file of files) {
        const src = readFileSync(file, 'utf8')
        const loc = this.rel(file)
        const inModule = /[\\/]modules[\\/]([^\\/]+)[\\/]/.exec(file)
        const name = basename(file)
        const isTest = /\.(test|spec)\.tsx?$/.test(name)

        if (inModule && /(^|[.\-/])service\.ts$/.test(name) && /from\s+['"]elysia['"]/.test(src))
          this.add('medium', 'service-imports-elysia', loc, 'Services must be framework-blind: no Elysia imports. Return a Result or throw a DomainError with a `status` property.')

        if (inModule && !isTest) {
          const ctxHandler = /\.(get|post|put|patch|delete|all)\(\s*['"`][^'"`]*['"`]\s*,\s*(async\s*)?\(?\s*(ctx|context|c)\s*[,)]/.exec(src)
          if (ctxHandler)
            this.add('medium', 'whole-context', `${loc}:${lineOf(src, ctxHandler.index)}`, 'Handler takes the whole Context. Destructure what you need ({ body, params, user }) and pass plain values to the service.')
          if (/\bimport\s+(type\s+)?\{[^}]*\bContext\b[^}]*\}\s+from\s+['"]elysia['"]/.test(src))
            this.add('medium', 'context-type', loc, 'Importing Elysia `Context` for a separate controller loses inference. Use the Elysia instance as the controller.')
          const errHelper = /\(\s*\{[^}]*\berror\b[^}]*\}\s*\)\s*=>[\s\S]{0,400}?\berror\(\s*\d{3}/.exec(src)
          if (errHelper)
            this.add('low', 'error-helper', `${loc}:${lineOf(src, errHelper.index)}`, 'The `error()` context helper is superseded by `status(code, body)`.')

          for (const call of routeCalls(src, ['post', 'put', 'patch'])) {
            if (!/\bbody\s*:/.test(call.body) && !/\bparse\s*:\s*['"]none['"]/.test(call.body))
              this.add('medium', 'route-without-body-schema', `${loc}:${lineOf(src, call.index)}`,
                `${call.method.toUpperCase()} route has no \`body\` schema. Validate input (t.Object / Standard Schema); it also types Eden clients.`)
          }

        }

        // Cross-module imports must go through the other module's public.ts.
        const own = inModule?.[1]
        const importRes = [
          /from\s+['"]\.\.\/(?!\.)([^/'"]+)\/([^'"]+)['"]/g, // sibling module: '../billing/service'
          /from\s+['"][^'"]*\bmodules\/([^/'"]+)\/([^'"]+)['"]/g, // anywhere: '../modules/billing/service'
        ]
        for (const re of importRes) {
          if (re === importRes[0] && !inModule) continue
          for (const m of src.matchAll(re)) {
            if (m[1] === own) continue
            if (own && m[1] && !isTest) moduleEdges.set(own, (moduleEdges.get(own) ?? new Set()).add(m[1]))
            if (!/^public(\.ts)?$/.test(m[2] ?? ''))
              this.add('medium', 'cross-module-import', `${loc}:${lineOf(src, m.index ?? 0)}`,
                `Imports modules/${m[1]}/${m[2]}. Outside ${m[1]}, only its public API (modules/${m[1]}/public) may be imported.`)
          }
        }

        const instances = [...src.matchAll(/(?:const|let)\s+(\w+)\s*=\s*new Elysia\b[^;\n]*;?\s*$/gm)]
        for (const m of instances) {
          const id = m[1]
          const unchained = new RegExp(`^\\s*${id}\\s*\\.(get|post|put|patch|delete|use|state|decorate|derive|resolve|guard|macro|onBeforeHandle|onError)\\(`, 'm').exec(src)
          if (unchained)
            this.add('medium', 'not-method-chained', `${loc}:${lineOf(src, unchained.index)}`,
              `\`${id}.${unchained[1]}(...)\` as a separate statement drops types. Always method-chain Elysia calls.`)
        }

        if (this.isApp(w) && !this.isServer(w)) {
          for (const server of serverNames) {
            const re = new RegExp(`import\\s+(?!type\\b)[^;'"]*?from\\s+['"]${server.replace(/[/@-]/g, '\\$&')}(\\/[^'"]*)?['"]`)
            const m = re.exec(src)
            if (m)
              this.add('high', 'client-runtime-import', `${loc}:${lineOf(src, m.index)}`,
                `Runtime import from server package ${server}. Use \`import type { App } from '${server}'\`; server code must never ship to clients.`)
          }
        }

        // Client apps (Next.js, Expo) must read NEXT_PUBLIC_*/EXPO_PUBLIC_* literally, so skip them.
        const inConfig = /[\\/](config|env)[\\/]|(^|[\\/])env\.ts$|config\.ts$/.test(file)
        const clientApp = this.isApp(w) && !this.isServer(w)
        if (!inConfig && !clientApp && !isTest && !/[\\/]scripts[\\/]/.test(file)) {
          const env = /process\.env\.[A-Z_]+/.exec(src)
          if (env)
            this.add('low', 'scattered-env', `${loc}:${lineOf(src, env.index)}`, 'Read environment variables once in a validated config module (TypeBox schema at boot), not ad hoc.')
        }

        const anys = src.match(/:\s*any\b|\bas\s+any\b|<any>/g)?.length ?? 0
        if (anys && !isTest) {
          anyCount += anys
          anyFile ||= loc
        }
      }
    }
    for (const cycle of findCycles(moduleEdges))
      this.add('medium', 'module-cycle', `modules/${cycle[0]}`,
        `Module dependency cycle: ${cycle.join(' → ')}. Keep modules acyclic: put what the downstream module needs in the job payload instead of calling back.`)
    if (anyCount)
      this.add('low', 'explicit-any', anyFile, `${anyCount} explicit \`any\` across the codebase (first in ${anyFile}). Use real types or \`unknown\` + narrowing.`)
  }

  private checkDocker() {
    const dockerfiles = walk(this.root, ['Dockerfile'])
    for (const file of dockerfiles) {
      const src = readFileSync(file, 'utf8')
      const loc = this.rel(file)
      const stages = src.split(/^FROM\s+/im).slice(1)
      const last = stages.at(-1) ?? ''
      const compiles = /--compile/.test(src)
      if (compiles && /^\S*alpine/i.test(last) && !/musl/.test(src))
        this.add('high', 'alpine-without-musl', loc, 'Compiled Bun binaries default to glibc; on Alpine use --target=bun-linux-x64-musl (or arm64-musl), or run on distroless/base.')
      if (/--bytecode/.test(src) && !/--format[= ]esm/.test(src))
        this.add('medium', 'bytecode-without-esm', loc, '`--bytecode` without `--format=esm` fails on top-level await. Add --format=esm.')
      if (!compiles && /(CMD|ENTRYPOINT)\s*\[?\s*"?bun"?[\s,]+("run"[\s,]+)?"?[^"\s]*\.ts/.test(last))
        this.add('low', 'runtime-typescript', loc, 'Final stage runs .ts with Bun. Compile a standalone binary (bun build --compile) for 2-3x less memory and no runtime deps.')
    }
  }

  private checkTooling(rootPkg: Record<string, any>) {
    const has = (f: string) => existsSync(join(this.root, f))
    const biome = has('biome.json') || has('biome.jsonc')
    if (!biome) this.add('low', 'no-biome', '.', 'No biome.json. Use Biome for lint + format (`biome ci .` in CI) instead of ESLint + Prettier.')
    const legacy = ['.eslintrc', '.eslintrc.json', '.eslintrc.js', 'eslint.config.js', 'eslint.config.mjs', '.prettierrc', 'prettier.config.js'].filter(has)
    if (biome && legacy.length) this.add('low', 'mixed-linters', legacy.join(', '), 'ESLint/Prettier config alongside Biome. Pick one (Biome).')
    const scripts = JSON.stringify(rootPkg.scripts ?? {}) + walk(join(this.root, '.github'), ['.yml', '.yaml']).map((f) => readFileSync(f, 'utf8')).join('\n')
    if (/\bbun\s+check\b/.test(scripts))
      this.add('medium', 'bun-check', 'package.json / CI', '`bun check` is not a Bun command. Type-check with `tsc --noEmit` per workspace (bun run --filter \'*\' typecheck).')
  }
}

function report(a: Auditor): string {
  const out = [`Bun/Elysia audit: ${a.root}`, `Workspaces: ${(a.facts.workspaces as string[]).join(', ')}`]
  if (!a.findings.length) return [...out, 'No findings.'].join('\n')
  for (const sev of SEVERITIES) {
    const group = a.findings.filter((f) => f.severity === sev)
    if (!group.length) continue
    out.push('', `${sev.toUpperCase()} (${group.length})`)
    for (const f of group) out.push(`  [${f.check}] ${f.location}: ${f.message}`)
  }
  out.push('', `Summary: ${SEVERITIES.map((s) => `${a.findings.filter((f) => f.severity === s).length} ${s}`).join(', ')}`)
  return out.join('\n')
}

function main(argv: string[]): number {
  let json = false
  let failOn = 'high'
  const positional: string[] = []
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i] ?? ''
    if (arg === '-h' || arg === '--help') usage(0)
    else if (arg === '--json') json = true
    else if (arg === '--fail-on') failOn = argv[++i] ?? ''
    else if (arg.startsWith('--fail-on=')) failOn = arg.split('=')[1] ?? ''
    else if (arg.startsWith('-')) {
      console.error(`Error: unknown option ${arg}`)
      usage(2)
    } else positional.push(arg)
  }
  if (!['high', 'medium', 'low', 'none'].includes(failOn)) {
    console.error(`Error: --fail-on must be one of high, medium, low, none (got "${failOn}")`)
    return 2
  }
  const root = resolve(positional[0] ?? '.')
  if (!existsSync(join(root, 'package.json'))) {
    console.error(`Error: '${root}' has no package.json. Pass the repository root.`)
    return 2
  }
  let auditor: Auditor
  try {
    auditor = new Auditor(root).run()
  } catch (error) {
    console.error(`Error: ${(error as Error).message}`)
    return 2
  }
  console.log(json ? JSON.stringify({ facts: auditor.facts, findings: auditor.findings }, null, 2) : report(auditor))
  if (failOn === 'none') return 0
  const threshold = SEVERITIES.indexOf(failOn as Severity)
  return auditor.findings.some((f) => SEVERITIES.indexOf(f.severity) <= threshold) ? 1 : 0
}

process.exit(main(process.argv.slice(2)))
