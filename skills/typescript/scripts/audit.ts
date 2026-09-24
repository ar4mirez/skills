#!/usr/bin/env node
/**
 * audit.ts: static anti-pattern scan for TypeScript projects (libraries, CLIs, Node services).
 *
 * Runs unchanged with `node scripts/audit.ts` (Node 22.18+/24 native type stripping) and
 * `bun scripts/audit.ts`. Uses only node: built-ins and erasable TypeScript syntax.
 *
 * Exit codes: 0 no findings at or above --fail-on, 1 findings, 2 bad input.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { basename, dirname, extname, join, relative, resolve, sep } from 'node:path'

const USAGE = `Usage: node scripts/audit.ts [options] PATH
       bun scripts/audit.ts [options] PATH

Statically scans a TypeScript project for anti-patterns: tsconfig options removed in
TypeScript 7 or missing strictness flags, any/as any, non-null !, non-erasable syntax
(enums, namespaces, parameter properties), @ts-ignore, floating promises (heuristic),
CommonJS, library packaging (exports map, types), unvalidated JSON, fetch without a
signal, console in libraries, swallowed errors, secrets, and deployment smells.

Options:
  --json               machine-readable output
  --fail-on LEVEL      exit 1 when a finding is at or above LEVEL:
                       high (default), medium, low, or none
  -h, --help           show this help

Exit codes: 0 ok, 1 findings at or above --fail-on, 2 bad input.`

type Severity = 'high' | 'medium' | 'low'

interface Finding {
  readonly check: string
  readonly severity: Severity
  readonly location: string
  readonly message: string
}

const RANK: Record<Severity, number> = { high: 3, medium: 2, low: 1 }
const SKIP_DIRS = new Set([
  'node_modules',
  'dist',
  'build',
  'out',
  'coverage',
  '.git',
  '.next',
  '.turbo',
  '.output',
  '.cache',
  'vendor',
])
const TS_EXT = new Set(['.ts', '.tsx', '.mts', '.cts'])

class UsageError extends Error {
  override readonly name = 'UsageError'
}

// ---------------------------------------------------------------- arguments

interface Options {
  readonly root: string
  readonly json: boolean
  readonly failOn: Severity | 'none'
}

function parseOptions(argv: readonly string[]): Options | 'help' {
  let json = false
  let failOn: Severity | 'none' = 'high'
  const positionals: string[] = []
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i] ?? ''
    if (arg === '-h' || arg === '--help') return 'help'
    if (arg === '--json') {
      json = true
    } else if (arg === '--fail-on' || arg.startsWith('--fail-on=')) {
      const value = arg.includes('=') ? arg.slice(arg.indexOf('=') + 1) : argv[++i]
      if (value !== 'high' && value !== 'medium' && value !== 'low' && value !== 'none') {
        throw new UsageError(`--fail-on needs high, medium, low, or none (got ${value ?? 'nothing'})`)
      }
      failOn = value
    } else if (arg.startsWith('-')) {
      throw new UsageError(`unknown option ${arg}`)
    } else {
      positionals.push(arg)
    }
  }
  if (positionals.length !== 1) throw new UsageError('expected exactly one PATH')
  const root = resolve(positionals[0] ?? '.')
  if (!existsSync(root) || !statSync(root).isDirectory()) throw new UsageError(`not a directory: ${root}`)
  return { root, json, failOn }
}

// ---------------------------------------------------------------- helpers

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) walk(join(dir, entry.name), out)
    } else if (entry.isFile()) {
      out.push(join(dir, entry.name))
    }
  }
  return out
}

/** Parses JSON with comments and trailing commas (tsconfig, biome.jsonc). */
function parseJsonc(text: string): unknown {
  let out = ''
  let inString = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    const next = text[i + 1]
    if (inString) {
      out += ch
      if (ch === '\\') out += text[++i] ?? ''
      else if (ch === '"') inString = false
    } else if (ch === '"') {
      inString = true
      out += ch
    } else if (ch === '/' && next === '/') {
      while (i < text.length && text[i] !== '\n') i++
      out += '\n'
    } else if (ch === '/' && next === '*') {
      i += 2
      while (i < text.length && !(text[i] === '*' && text[i + 1] === '/')) i++
      i++
    } else {
      out += ch
    }
  }
  return JSON.parse(out.replace(/,(\s*[}\]])/g, '$1'))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function readJson(file: string): Record<string, unknown> | undefined {
  try {
    const parsed = parseJsonc(readFileSync(file, 'utf8'))
    return isRecord(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
}

/**
 * Blanks out comments, strings, template literals, and regex literals (keeping
 * newlines) so code checks don't match text inside them.
 */
function codeOnly(src: string): string {
  let out = ''
  let i = 0
  let last = '' // last significant code character, to tell regex from division
  const blank = (s: string): string => s.replace(/[^\n]/g, ' ')
  while (i < src.length) {
    const ch = src[i] ?? ''
    const next = src[i + 1] ?? ''
    if (ch === '/' && next === '/') {
      const end = src.indexOf('\n', i)
      const stop = end === -1 ? src.length : end
      out += blank(src.slice(i, stop))
      i = stop
    } else if (ch === '/' && next === '*') {
      const end = src.indexOf('*/', i + 2)
      const stop = end === -1 ? src.length : end + 2
      out += blank(src.slice(i, stop))
      i = stop
    } else if (ch === '"' || ch === "'" || ch === '`') {
      let j = i + 1
      while (j < src.length && src[j] !== ch) {
        if (src[j] === '\\') j++
        else if (ch !== '`' && src[j] === '\n') break
        j++
      }
      out += `${ch}${blank(src.slice(i + 1, j))}${ch}`
      i = j + 1
      last = 'a'
    } else if (ch === '/' && (last === '' || '(,=:[!&|?{};+-*%<>~^'.includes(last))) {
      let j = i + 1
      let inClass = false
      while (j < src.length && src[j] !== '\n') {
        if (src[j] === '\\') j++
        else if (src[j] === '[') inClass = true
        else if (src[j] === ']') inClass = false
        else if (src[j] === '/' && !inClass) break
        j++
      }
      out += `/${blank(src.slice(i + 1, j))}/`
      i = j + 1
      last = 'a'
    } else {
      out += ch
      if (!/\s/.test(ch)) last = ch
      i++
    }
  }
  return out
}

/** Returns the text between the parenthesis at `open` and its match. */
function callArgs(code: string, open: number): string {
  let depth = 0
  for (let i = open; i < code.length; i++) {
    if (code[i] === '(') depth++
    else if (code[i] === ')' && --depth === 0) return code.slice(open + 1, i)
  }
  return code.slice(open + 1)
}

function lineOf(text: string, index: number): number {
  let line = 1
  for (let i = 0; i < index; i++) if (text.charCodeAt(i) === 10) line++
  return line
}

// ---------------------------------------------------------------- project model

interface Pkg {
  readonly dir: string
  readonly file: string
  readonly json: Record<string, unknown>
  readonly isLibrary: boolean
}

function loadPackages(files: readonly string[]): Pkg[] {
  const pkgs: Pkg[] = []
  for (const file of files) {
    if (basename(file) !== 'package.json') continue
    const json = readJson(file)
    if (!json) continue
    const dir = dirname(file)
    // Apps are deployables, not libraries; a publishable package declares an entry point or lives in packages/.
    const publishable =
      ['exports', 'main', 'module', 'types', 'typings', 'files', 'publishConfig'].some((k) => k in json) ||
      /[/\\]packages[/\\][^/\\]+$/.test(dir)
    const isLibrary =
      typeof json.name === 'string' &&
      json.private !== true &&
      !('workspaces' in json) &&
      !/[/\\]apps[/\\]/.test(dir + sep) &&
      publishable
    pkgs.push({ dir, file, json, isLibrary })
  }
  return pkgs.sort((a, b) => b.dir.length - a.dir.length)
}

function owningPackage(pkgs: readonly Pkg[], file: string): Pkg | undefined {
  return pkgs.find((p) => file === p.dir || file.startsWith(p.dir + sep))
}

const isTest = (file: string): boolean =>
  /(\.|_)(test|spec|test-d)\.[cm]?tsx?$/.test(file) || /[/\\](__tests__|tests?|fixtures?|e2e)[/\\]/.test(file)
const isScriptOrBin = (file: string): boolean =>
  /[/\\](scripts|bin|cli)[/\\]/.test(file) || /^(main|cli)\.[cm]?ts$/.test(basename(file))
const isConfigFile = (file: string): boolean => /\.config\.[cm]?ts$/.test(file)

// ---------------------------------------------------------------- checks

const REMOVED_OPTIONS: ReadonlyArray<readonly [string, (v: unknown) => boolean, string]> = [
  ['baseUrl', () => true, 'use "paths" relative to the tsconfig, or package.json "imports" (#/*)'],
  [
    'moduleResolution',
    (v) => typeof v === 'string' && /^(node|node10|classic)$/i.test(v),
    'use "nodenext" (Node) or "bundler"',
  ],
  ['target', (v) => typeof v === 'string' && /^es(3|5)$/i.test(v), 'target ES2022 or later'],
  [
    'module',
    (v) => typeof v === 'string' && /^(amd|umd|system|systemjs|none)$/i.test(v),
    'use nodenext or esnext',
  ],
  ['outFile', () => true, 'bundle with tsdown/rolldown instead'],
  ['downlevelIteration', () => true, 'delete it; ES5 emit is gone'],
  ['esModuleInterop', (v) => v === false, 'delete it; it is always on'],
  ['allowSyntheticDefaultImports', (v) => v === false, 'delete it; it is always on'],
  ['alwaysStrict', (v) => v === false, 'delete it; strict mode is always on'],
]

/** Merges compilerOptions along relative `extends` chains. Returns undefined options when unresolvable. */
function resolveTsconfig(file: string, seen = new Set<string>()): Record<string, unknown> | undefined {
  if (seen.has(file)) return {}
  seen.add(file)
  const json = readJson(file)
  if (!json) return undefined
  let merged: Record<string, unknown> = {}
  const ext = json.extends
  const bases = typeof ext === 'string' ? [ext] : Array.isArray(ext) ? ext : []
  for (const base of bases) {
    if (typeof base !== 'string') continue
    if (!base.startsWith('.')) return undefined // package-provided base: can't see its flags
    const path = resolve(dirname(file), base.endsWith('.json') ? base : `${base}.json`)
    const parent = existsSync(path) ? resolveTsconfig(path, seen) : undefined
    if (!parent) return undefined
    merged = { ...merged, ...parent }
  }
  const own = json.compilerOptions
  return { ...merged, ...(isRecord(own) ? own : {}) }
}

function checkTsconfig(file: string, rel: string, pkg: Pkg | undefined, add: AddFn): void {
  const json = readJson(file)
  if (!json) {
    add('tsconfig-unparseable', 'medium', rel, 'tsconfig could not be parsed')
    return
  }
  const own = isRecord(json.compilerOptions) ? json.compilerOptions : {}
  for (const [key, matches, fix] of REMOVED_OPTIONS) {
    if (key in own && matches(own[key])) {
      add(
        'tsconfig-removed-option',
        'high',
        rel,
        `"${key}": ${JSON.stringify(own[key])} is removed in TypeScript 7 (TS5102/TS5108); ${fix}`,
      )
    }
  }
  if ('ignoreDeprecations' in own) {
    add(
      'tsconfig-ignore-deprecations',
      'medium',
      rel,
      '"ignoreDeprecations" only postpones TS 6 deprecations; TS 7 removed those options',
    )
  }
  if (typeof own.module === 'string' && /^commonjs$/i.test(own.module)) {
    add(
      'tsconfig-commonjs',
      'low',
      rel,
      '"module": "commonjs" emits CJS; new code is ESM (use nodenext or esnext)',
    )
  }
  if (own.strict === false) {
    add(
      'tsconfig-not-strict',
      'high',
      rel,
      '"strict": false turns off the checks that make TypeScript worth it',
    )
  }
  const opts = resolveTsconfig(file)
  if (!opts || basename(file) !== 'tsconfig.json') return
  if (opts.noUncheckedIndexedAccess !== true) {
    add(
      'tsconfig-missing-flag',
      'medium',
      rel,
      'enable "noUncheckedIndexedAccess": index access returns T | undefined',
    )
  }
  if (opts.verbatimModuleSyntax !== true) {
    add(
      'tsconfig-missing-flag',
      'low',
      rel,
      'enable "verbatimModuleSyntax" so type-only imports are explicit and erasable',
    )
  }
  if (opts.erasableSyntaxOnly !== true) {
    add(
      'tsconfig-missing-flag',
      'low',
      rel,
      'enable "erasableSyntaxOnly" so code runs under Node/Bun type stripping',
    )
  }
  if (pkg?.isLibrary && opts.isolatedDeclarations !== true) {
    add(
      'tsconfig-missing-flag',
      'low',
      rel,
      'libraries: enable "isolatedDeclarations" for fast, explicit .d.ts emit',
    )
  }
}

function checkPackage(pkg: Pkg, rel: string, add: AddFn): void {
  const j = pkg.json
  const scripts = isRecord(j.scripts) ? j.scripts : {}
  for (const [name, cmd] of Object.entries(scripts)) {
    if (typeof cmd !== 'string') continue
    if (/--experimental-(strip|transform)-types/.test(cmd)) {
      add(
        'experimental-strip-flag',
        'low',
        `${rel} (scripts.${name})`,
        'type stripping is stable in Node 24.12+; drop --experimental-*-types (use erasable syntax instead of transform-types)',
      )
    }
    if (/\bts-node\b/.test(cmd)) {
      add(
        'legacy-runner',
        'low',
        `${rel} (scripts.${name})`,
        'run .ts directly with node (type stripping) or bun instead of ts-node',
      )
    }
  }
  const deps = {
    ...(isRecord(j.dependencies) ? j.dependencies : {}),
    ...(isRecord(j.devDependencies) ? j.devDependencies : {}),
  }
  const legacy: Record<string, string> = {
    tslint: 'deprecated since 2019; use Biome',
    'ts-node': 'use node (type stripping) or bun',
    'node-fetch': 'fetch is global in Node 18+',
    request: 'deprecated; use fetch',
    dotenv: 'use node --env-file / --env-file-if-exists (or Bun, which loads .env)',
    moment: 'in maintenance; use Temporal (when available) or date-fns',
  }
  for (const [name, why] of Object.entries(legacy)) {
    if (name in deps) add('legacy-dependency', 'low', rel, `${name}: ${why}`)
  }
  if ('workspaces' in j) return
  if (j.private === true) {
    if (j.type !== 'module') add('package-not-esm', 'low', rel, 'set "type": "module"; new code is ESM')
    return
  }
  if (!pkg.isLibrary) return
  if (j.type !== 'module')
    add('package-not-esm', 'medium', rel, 'libraries: set "type": "module" and ship ESM')
  const exp = j.exports
  if (exp === undefined) {
    add(
      'library-no-exports',
      'high',
      rel,
      'no "exports" map: consumers can deep-import internals and types may not resolve under nodenext',
    )
    return
  }
  const text = JSON.stringify(exp)
  if (!/"types"/.test(text) && typeof j.types !== 'string') {
    add(
      'library-no-types',
      'high',
      rel,
      'exports has no "types" condition and no top-level "types": TS consumers get any',
    )
  }
  const firstKeyOrder = (o: unknown): void => {
    if (!isRecord(o)) return
    const keys = Object.keys(o)
    if (keys.includes('types') && keys[0] !== 'types' && !keys[0]?.startsWith('.')) {
      add('types-condition-order', 'medium', rel, '"types" must be the first condition in each exports entry')
    }
    for (const v of Object.values(o)) firstKeyOrder(v)
  }
  firstKeyOrder(exp)
  if (/\.ts"/.test(text.replace(/\.d\.[cm]?ts"/g, ''))) {
    add(
      'library-exports-source',
      'medium',
      rel,
      'exports point at .ts source: Node refuses to strip types under node_modules; publish built JS + .d.ts',
    )
  }
  if (!Array.isArray(j.files))
    add(
      'library-no-files',
      'low',
      rel,
      'add "files" (e.g. ["dist"]) so tests and sources stay out of the tarball',
    )
}

type AddFn = (check: string, severity: Severity, location: string, message: string) => void

const SECRET_RE =
  /(['"`])(sk_live_[0-9a-zA-Z]{16,}|ghp_[0-9A-Za-z]{30,}|github_pat_[0-9A-Za-z_]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[0-9A-Za-z-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)/
const SECRET_ASSIGN_RE =
  /\b(password|passwd|secret|api_?key|apiKey|token|auth_?token)\b\s*[:=]\s*(['"`])([^'"`\s]{8,})\2/i

function checkSource(file: string, rel: string, pkg: Pkg | undefined, add: AddFn): void {
  const raw = readFileSync(file, 'utf8')
  const code = codeOnly(raw)
  const rawLines = raw.split('\n')
  const lines = code.split('\n')
  const test = isTest(file)
  const at = (n: number): string => `${rel}:${n}`
  const inLibrarySrc = pkg?.isLibrary === true && !test && !isScriptOrBin(file) && !isConfigFile(file)

  // Comment directives (raw text, since they live in comments).
  rawLines.forEach((line, i) => {
    if (/\/\/\s*@ts-nocheck|\/\*\s*@ts-nocheck/.test(line))
      add('ts-nocheck', 'high', at(i + 1), '@ts-nocheck disables checking for the whole file')
    if (/(\/\/|\/\*)\s*@ts-ignore/.test(line)) {
      add(
        'ts-ignore',
        'medium',
        at(i + 1),
        'use @ts-expect-error with a reason: it fails once the error is gone',
      )
    }
    const expect = /(\/\/|\/\*)\s*@ts-expect-error(.*)$/.exec(line)
    if (expect && !/[a-z]{3,}/i.test((expect[2] ?? '').replace(/\*\//, ''))) {
      add('ts-expect-error-no-reason', 'low', at(i + 1), 'say why: // @ts-expect-error: <reason>')
    }
    if (!test && (SECRET_RE.test(line) || SECRET_ASSIGN_RE.test(line))) {
      const m = SECRET_ASSIGN_RE.exec(line)
      const placeholder =
        m && /^(x+|\*+|changeme|example|placeholder|your[-_].*|<.*>|\$\{.*)$/i.test(m[3] ?? '')
      if (!placeholder)
        add(
          'hardcoded-secret',
          'high',
          at(i + 1),
          'hard-coded credential: load it from the environment or a secret store',
        )
    }
  })

  // Names of async functions declared in this file, for the floating-promise heuristic.
  const asyncNames = new Set<string>()
  for (const m of code.matchAll(/\basync\s+function\s*\*?\s*([A-Za-z_$][\w$]*)/g)) asyncNames.add(m[1] ?? '')
  for (const m of code.matchAll(/\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*async\b/g))
    asyncNames.add(m[1] ?? '')
  for (const m of code.matchAll(
    /^\s*(?:(?:public|private|protected|static|override)\s+)*async\s+([A-Za-z_$][\w$]*)\s*[(<]/gm,
  )) {
    asyncNames.add(m[1] ?? '')
  }
  asyncNames.delete('')

  const lineStarts: number[] = [0]
  for (let k = 0; k < code.length; k++) if (code[k] === '\n') lineStarts.push(k + 1)
  lines.forEach((line, i) => {
    const n = i + 1
    if (/\bas\s+any\b/.test(line))
      add('as-any', 'medium', at(n), '`as any` switches off checking; narrow from unknown or fix the type')
    else if (/(:\s*any\b(?!\s*\w)|<any>|\bany\[\]|[<,]\s*any\s*[>,])/.test(line)) {
      add('explicit-any', 'medium', at(n), 'use unknown and narrow (or a real type) instead of any')
    }
    if (/[\w$)\]]!(?!=)(?=[.[(),;:\s]|$)/.test(line)) {
      add(
        'non-null-assertion',
        'medium',
        at(n),
        'non-null `!` hides a possible undefined; narrow with a check or throw a clear error',
      )
    }
    if (/^\s*(export\s+)?(const\s+)?enum\s+[A-Za-z_$]/.test(line)) {
      add(
        'enum',
        'medium',
        at(n),
        'enums are not erasable (Node type stripping rejects them); use an `as const` object + union type',
      )
    }
    if (/^\s*(export\s+)?(namespace|module)\s+[A-Za-z_$][\w$.]*\s*\{/.test(line)) {
      add('namespace', 'medium', at(n), 'runtime namespaces are not erasable; use ES modules')
    }
    const ctor = /\bconstructor\s*\(/.exec(line)
    if (
      ctor &&
      /\b(private|public|protected|readonly)\s+[A-Za-z_$]/.test(
        callArgs(lines.slice(i, i + 12).join('\n'), line.indexOf('(', ctor.index)),
      )
    ) {
      add(
        'parameter-property',
        'medium',
        at(n),
        'parameter properties are not erasable; declare the field and assign it in the constructor',
      )
    }
    if (/\brequire\s*\(\s*['"`]/.test(line) || /\bmodule\.exports\b|^\s*exports\.[\w$]+\s*=/.test(line)) {
      add('commonjs', 'medium', at(n), 'CommonJS in new code: use import/export (ESM)')
    }
    if (/\beval\s*\(|\bnew\s+Function\s*\(/.test(line))
      add('eval', 'high', at(n), 'eval/new Function runs strings as code')
    if (
      /\bJSON\.parse\s*\([^;]*\)\s*as\s+(?!unknown\b|const\b)[A-Z{[]/.test(line) ||
      /\.json\(\)\)?\s*as\s+(?!unknown\b)[A-Z{[]/.test(line)
    ) {
      add(
        'unvalidated-json',
        'medium',
        at(n),
        'casting parsed JSON trusts external input; parse it with a schema (Zod) instead',
      )
    } else if (/:\s*[A-Z][\w<>[\], ]*\s*=\s*(await\s+)?(JSON\.parse\(|[\w.]+\.json\(\))/.test(line)) {
      add(
        'unvalidated-json',
        'medium',
        at(n),
        'annotating parsed JSON is an unchecked cast; validate with a schema at the boundary',
      )
    }
    if (inLibrarySrc && /\bconsole\.(log|info|debug|warn|error|trace)\s*\(/.test(line)) {
      add(
        'library-console',
        'medium',
        at(n),
        'libraries must not write to the console; return values, throw, or accept a logger',
      )
    }
    if (/\bthrow\s+(['"`]|\{|\d)/.test(line))
      add('throw-literal', 'medium', at(n), 'throw Error objects (with a cause), not strings or objects')
    if (/\bcatch\s*(\([^)]*\))?\s*\{\s*\}/.test(line))
      add(
        'empty-catch',
        'medium',
        at(n),
        'empty catch swallows the error; handle, rethrow with a cause, or comment why',
      )

    // Floating promises: a bare call statement to a known-async function, fetch, or Promise combinator.
    const stmt = /^\s*(?:this\.)?([A-Za-z_$][\w$]*)(?:\.[A-Za-z_$][\w$]*)*\s*(?:<[^>]*>)?\(/.exec(line)
    if (stmt && !/^\s*(await|return|void|yield|throw)\b/.test(line)) {
      const callee = stmt[1] ?? ''
      // Only a complete call statement counts: `save(x)` or `save(x);`, not a method
      // signature (`save(x): Promise<T>`) or declaration (`save(x) {`).
      const open = (lineStarts[i] ?? 0) + stmt[0].length - 1
      const rest = code.slice(open + callArgs(code, open).length + 2).split('\n')[0] ?? ''
      const handled = /\.catch\(/.test(line) || !/^\s*;?\s*$/.test(rest)
      const floating =
        (asyncNames.has(callee) || /^\s*(fetch|Promise\.(all|allSettled|race|any))\s*\(/.test(line)) &&
        !handled
      if (floating) {
        add(
          'floating-promise',
          'medium',
          at(n),
          'promise is neither awaited nor returned: rejections become unhandled; await it or prefix `void` with a .catch',
        )
      }
    }
  })

  // fetch without an AbortSignal (multi-line aware).
  for (const m of code.matchAll(/(?<![\w$.])(?:globalThis\.)?fetch\s*\(/g)) {
    const open = (m.index ?? 0) + m[0].length - 1
    if (!/\bsignal\b/.test(callArgs(code, open))) {
      add(
        'fetch-no-signal',
        'medium',
        at(lineOf(code, m.index ?? 0)),
        'fetch without a signal can hang forever; pass signal: AbortSignal.timeout(ms) (or AbortSignal.any)',
      )
    }
  }

  // Rethrowing inside catch without { cause }.
  for (const m of code.matchAll(/\bcatch\s*\(\s*([A-Za-z_$][\w$]*)[^)]*\)\s*\{/g)) {
    const start = (m.index ?? 0) + m[0].length
    let depth = 1
    let end = start
    while (end < code.length && depth > 0) {
      if (code[end] === '{') depth++
      else if (code[end] === '}') depth--
      end++
    }
    const body = code.slice(start, end)
    for (const t of body.matchAll(/\bthrow\s+new\s+(?:[A-Z]\w*)?Error\s*\(/g)) {
      const args = callArgs(body, (t.index ?? 0) + t[0].length - 1)
      if (!/\bcause\b/.test(args) && !new RegExp(`\\b${m[1]}\\b`).test(args)) {
        add(
          'error-without-cause',
          'low',
          at(lineOf(code, start + (t.index ?? 0))),
          `new error loses the original; pass { cause: ${m[1]} }`,
        )
      }
    }
  }
}

function checkProject(root: string, files: readonly string[], add: AddFn): void {
  const has = (name: string): boolean => existsSync(join(root, name))
  const lockfiles = ['pnpm-lock.yaml', 'bun.lock', 'package-lock.json', 'yarn.lock'].filter(has)
  if (has('bun.lockb'))
    add(
      'binary-lockfile',
      'low',
      'bun.lockb',
      'binary lockfile: run `bun install --save-text-lockfile` and commit bun.lock',
    )
  if (lockfiles.length === 0 && !has('bun.lockb'))
    add('no-lockfile', 'medium', '.', 'no lockfile committed: installs are not reproducible')
  if (lockfiles.length > 1)
    add(
      'multiple-lockfiles',
      'medium',
      '.',
      `several lockfiles (${lockfiles.join(', ')}): pick one package manager`,
    )
  const linters = [
    'biome.json',
    'biome.jsonc',
    'eslint.config.js',
    'eslint.config.mjs',
    'eslint.config.ts',
    '.oxlintrc.json',
    'oxlint.config.ts',
  ]
  if (!linters.some(has)) add('no-linter', 'low', '.', 'no Biome (or ESLint/oxlint) config at the root')
  if (!files.some((f) => basename(f) === 'tsconfig.json'))
    add('no-tsconfig', 'medium', '.', 'no tsconfig.json: nothing type-checks this code')

  // Services: something listens but nothing handles SIGTERM.
  const sources = files.filter((f) => TS_EXT.has(extname(f)) && !f.endsWith('.d.ts') && !isTest(f))
  const listens = sources.find((f) =>
    /\b(serve|listen)\s*\(\s*\{?[^)]*\b(port|fetch)\b|\.listen\s*\(\s*\d|\.listen\s*\(\s*\{/.test(
      codeOnly(readFileSync(f, 'utf8')),
    ),
  )
  if (listens && !sources.some((f) => /SIGTERM/.test(readFileSync(f, 'utf8')))) {
    add(
      'no-graceful-shutdown',
      'medium',
      relative(root, listens),
      'server never handles SIGTERM: deploys drop in-flight requests; close the server, then exit',
    )
  }

  for (const f of files) {
    const name = basename(f)
    if (!/^Dockerfile/.test(name)) continue
    const text = readFileSync(f, 'utf8')
    const stages = text.split(/^FROM\s+/im)
    const final = stages[stages.length - 1] ?? ''
    const image = final.split(/\s/)[0] ?? ''
    if (/\b(ts-node|tsx)\b/.test(final))
      add(
        'docker-ts-runner',
        'medium',
        relative(root, f),
        'final image runs ts-node/tsx: run node on .ts directly (type stripping) or ship built JS',
      )
    if (!/distroless|nonroot|chainguard/.test(image) && !/^\s*USER\s+(?!root)/im.test(final)) {
      add(
        'docker-root',
        'low',
        relative(root, f),
        `final stage (${image}) runs as root: use distroless nodejs :nonroot or add USER node`,
      )
    }
    if (
      /^\s*(RUN|CMD).*\b(npm|pnpm|yarn)\s+(install|i)\b(?!.*(--prod|--omit=dev|--frozen-lockfile|ci|-g\b|--global))/im.test(
        text,
      )
    ) {
      add(
        'docker-unlocked-install',
        'low',
        relative(root, f),
        'install with --frozen-lockfile (or npm ci) in images',
      )
    }
  }
}

// ---------------------------------------------------------------- main

function audit(root: string): Finding[] {
  const files = walk(root)
  const pkgs = loadPackages(files)
  const hasTs =
    files.some((f) => TS_EXT.has(extname(f))) || files.some((f) => basename(f) === 'tsconfig.json')
  if (!hasTs && pkgs.length === 0)
    throw new UsageError(
      `no TypeScript project found in ${root} (no .ts files, tsconfig.json, or package.json)`,
    )
  const findings: Finding[] = []
  const add: AddFn = (check, severity, location, message) =>
    findings.push({ check, severity, location, message })

  for (const pkg of pkgs) checkPackage(pkg, relative(root, pkg.file) || 'package.json', add)
  for (const file of files) {
    const rel = relative(root, file)
    const name = basename(file)
    if (/^tsconfig.*\.json$/.test(name)) checkTsconfig(file, rel, owningPackage(pkgs, file), add)
    else if (TS_EXT.has(extname(file)) && !/\.d\.[cm]?ts$/.test(name))
      checkSource(file, rel, owningPackage(pkgs, file), add)
    else if (/\.(cjs|cts)$/.test(name) && !/\.config\.cjs$/.test(name))
      add('commonjs', 'low', rel, 'CommonJS file in new code: prefer ESM')
  }
  checkProject(root, files, add)
  return findings.sort(
    (a, b) =>
      RANK[b.severity] - RANK[a.severity] || a.location.localeCompare(b.location, 'en', { numeric: true }),
  )
}

function report(root: string, findings: readonly Finding[]): string {
  const out: string[] = [`TypeScript audit: ${root}`, '']
  for (const sev of ['high', 'medium', 'low'] as const) {
    const group = findings.filter((f) => f.severity === sev)
    if (group.length === 0) continue
    out.push(`${sev.toUpperCase()} (${group.length})`)
    for (const f of group) out.push(`  [${f.check}] ${f.location}: ${f.message}`)
    out.push('')
  }
  const count = (s: Severity): number => findings.filter((f) => f.severity === s).length
  out.push(`Summary: ${count('high')} high, ${count('medium')} medium, ${count('low')} low`)
  return out.join('\n')
}

function main(argv: readonly string[]): number {
  let options: Options | 'help'
  try {
    options = parseOptions(argv)
  } catch (error) {
    if (!(error instanceof UsageError)) throw error
    process.stderr.write(`audit: ${error.message}\n\n${USAGE}\n`)
    return 2
  }
  if (options === 'help') {
    process.stdout.write(`${USAGE}\n`)
    return 0
  }
  let findings: Finding[]
  try {
    findings = audit(options.root)
  } catch (error) {
    if (!(error instanceof UsageError)) throw error
    process.stderr.write(`audit: ${error.message}\n`)
    return 2
  }
  if (options.json) {
    process.stdout.write(`${JSON.stringify({ root: options.root, findings }, null, 2)}\n`)
  } else {
    process.stdout.write(`${report(options.root, findings)}\n`)
  }
  const threshold = options.failOn === 'none' ? Number.POSITIVE_INFINITY : RANK[options.failOn]
  return findings.some((f) => RANK[f.severity] >= threshold) ? 1 : 0
}

process.exitCode = main(process.argv.slice(2))
