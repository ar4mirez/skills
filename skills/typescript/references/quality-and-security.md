# Quality gate and security

## Contents
- The gate
- Biome (format + lint)
- Type-aware linting on TypeScript 7
- CI workflow
- Dependency and supply-chain hygiene
- Secure coding
- Review checklist

## The gate

Zero warnings, in this order (fail fast on the cheap checks):

```bash
pnpm install --frozen-lockfile
pnpm build                               # libraries (so dependents type-check against dist)
pnpm typecheck                           # tsc --noEmit per package (TS 7)
pnpm lint                                # biome ci . && oxlint
pnpm test                                # vitest run (coverage thresholds where configured)
pnpm --filter './packages/*' run lint:pkg  # publint --strict + attw
pnpm audit --audit-level high
```

Plus this skill's audit for things no linter covers (tsconfig drift,
packaging, Docker, missing shutdown): `node scripts/audit.ts <repo>` from
the skill directory.

## Biome (format + lint)

Default for formatting and linting: one fast binary, one config
(`assets/biome.json`), no plugin graph. Biome 2.5:
- `"preset": "recommended"` (the old `recommended: true` is deprecated;
  `biome migrate` rewrites it).
- `biome ci .` in CI (read-only, fails on unformatted files);
  `biome check --write .` locally.
- House rules on top of recommended: `noExplicitAny`, `noNonNullAssertion`,
  `useImportType`/`useExportType`, `noEnum`, `noNamespace`,
  `noParameterProperties` (keep code erasable), `useNodejsImportProtocol`,
  `noConsole` (overrides for CLIs and scripts), and the type-aware nursery
  rules `noFloatingPromises` and `noMisusedPromises`.

What Biome's type inference does and doesn't cover (Biome 2.5.14,
verified with probe files):
- Catches floating calls to async functions and methods **declared in your
  own files**, bare `fetch()`, `Promise.all(...)`, `.then()` without a
  handler, async callbacks passed to `forEach`, and promises in `if`
  conditions.
- **Misses** floating calls to async functions **imported from packages**
  (a workspace library's `retry()` in the probe), because it doesn't infer
  through dependency `.d.ts` files.
- Both rules are in `nursery`: behavior can change in minor releases; pin
  Biome exactly.
- No equivalents yet for most typescript-eslint type-aware rules
  (`no-unsafe-*`, `restrict-template-expressions`,
  `switch-exhaustiveness-check`, `no-unnecessary-condition`).

## Type-aware linting on TypeScript 7

**typescript-eslint 8.x does not support TypeScript 7**: its peer range is
`typescript <6.1.0`, TS 7.0 has no JS API, and the maintainers closed the
TS 7 support issue as not planned for now. Options, in order:

1. **oxlint type-aware (default when you need it).** `oxlint` +
   `oxlint-tsgolint@7` (built on TS 7's Go compiler; 59 of 61
   typescript-eslint type-aware rules; stable since 2026-07). Run it
   *next to* Biome with only the type-aware rules on
   (`assets/oxlintrc.json`: `"categories": { "correctness": "off" }`,
   `"options": { "typeAware": true }`, then the rules). Verified: it flags
   the cross-package floating promise Biome missed, and the reference
   workspace passes clean. Build workspace libraries first so their `.d.ts`
   exist.
2. **typescript-eslint on a TS 6 side install** (`"typescript":
   "npm:@typescript/typescript6@6.0.2"`, TS 7 as `@typescript/native`) only
   if you depend on ESLint-only plugins. You'll run two compilers that
   occasionally disagree.

Rules worth enabling in oxlint: `no-floating-promises`,
`no-misused-promises`, `await-thenable`, `switch-exhaustiveness-check`,
`only-throw-error`, `no-unnecessary-type-assertion`,
`restrict-template-expressions`. Skip `prefer-promise-reject-errors` if you
reject with `signal.reason` (the platform's own convention).

## CI workflow

`assets/github-ci.yml`: one `check` job (the gate), a library matrix on
Node 22/24/26, and a Bun smoke import. Pinned majors verified 2026-09:
`actions/checkout@v7`, `pnpm/action-setup@v6` (reads `packageManager`),
`actions/setup-node@v7` with `cache: pnpm`, `oven-sh/setup-bun@v2`.
`permissions: contents: read`, a `concurrency` group, and timeouts on
every job. Pin third-party actions by commit SHA in high-security repos.

## Dependency and supply-chain hygiene

- One lockfile, committed; `--frozen-lockfile` everywhere automated.
- pnpm 11+ defaults protect you: `minimumReleaseAge` (1 day) and
  `strictDepBuilds` with an explicit `allowBuilds` map. Review
  auto-added `minimumReleaseAgeExclude` entries; don't blanket-allow
  builds.
- `pnpm audit --audit-level high` in CI; Dependabot or Renovate for
  updates, grouped by catalog.
- Every dependency must earn its lifetime cost: prefer platform APIs
  (`fetch`, `AbortSignal`, `crypto.randomUUID`, `structuredClone`,
  `node:util` `parseArgs`/`styleText`, `--env-file`) over packages.
- Publish with provenance (`npm publish --provenance` or trusted
  publishing from CI); see `libraries.md`.

## Secure coding

- **Validate every boundary** with a schema (`idioms.md`); use
  `z.strictObject` for request bodies to block mass assignment; restrict URL
  schemes (`z.url({ protocol: /^https?$/ })`) before redirecting or
  fetching (open redirect, SSRF, `javascript:` URLs).
- **SSRF**: server-side fetches of user-supplied URLs go through an
  allowlist of hosts; block private ranges when the host is arbitrary.
- **SQL**: parameterized queries only (the driver's tagged template or `$1`
  placeholders); never string-build SQL.
- **Prototype pollution**: don't deep-merge untrusted objects; parse with
  a schema (which drops `__proto__`), use `Object.create(null)` or `Map`
  for dictionaries keyed by user input.
- **Secrets**: from the environment (parsed once in `env.ts`), never in
  code or images; `.env*` in `.gitignore` and `.dockerignore`; don't log
  whole config objects or request headers (pino `redact` for
  `authorization`, `cookie`).
- **Crypto**: `crypto.randomUUID()`/`crypto.getRandomValues()` for tokens,
  never `Math.random()`; `crypto.timingSafeEqual` for secret comparisons;
  Argon2id or scrypt (`node:crypto` `scrypt`) for passwords.
- **Errors to clients**: generic messages; details go to logs.
- **eval / new Function / vm with user input**: never.
- **Regex DoS**: avoid nested quantifiers on user input; bound input
  length before matching.

## Review checklist

High (block the merge):
- Unvalidated external input (casts of `JSON.parse`/`res.json()`, raw
  `process.env` reads in business code).
- Floating promises; `forEach(async …)`.
- Hard-coded secrets; SQL string building; SSRF/open redirect.
- Service without graceful shutdown or with no timeouts on outbound calls.
- Library without an `exports` map or types; CJS-only new package.
- tsconfig with removed TS 7 options or `strict: false`.

Medium:
- `any`, `as any`, `!`, `@ts-ignore`; enums, namespaces, parameter
  properties.
- Errors rethrown without `cause`; empty `catch`; thrown strings.
- `fetch` without a signal; unbounded `Promise.all` over input-sized
  arrays.
- `console.log` in library code; `process.exit` outside `main`.
- Missing tests for error paths; `expectTypeOf` not covered by `tsc`.

Low:
- Legacy dependencies (ts-node, node-fetch, dotenv, tslint, moment).
- Default exports, `export *` public entries, per-folder barrels.
- Missing `noUncheckedIndexedAccess`/`verbatimModuleSyntax`/
  `erasableSyntaxOnly`.
