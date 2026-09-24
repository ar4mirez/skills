# ar4mirez/skills

This repo holds portable [Agent Skills](https://agentskills.io): folders of
instructions, references, templates, and scripts that give AI agents real
domain expertise. Every skill follows the open
[Agent Skills specification](https://agentskills.io/specification), so it
works in any compatible client (Claude Code, Claude.ai, Codex, Cursor, GitHub
Copilot, VS Code, and others).

## Skills

| Skill | What it does |
|---|---|
| [`go`](skills/go/SKILL.md) | An opinionated Go 1.27 engineer. It builds standard-library-first services and CLIs (net/http routing, slog, json/v2) with a `cmd/` + `internal/` layout, pgx + sqlc + goose, errgroup concurrency, and table, fuzz, and synctest tests. The gate is golangci-lint v2 and govulncheck, and it ships static binaries on distroless with Kamal. It bundles a Go audit tool and a scaffolder. |
| [`rust`](skills/rust/SKILL.md) | An opinionated Rust 1.98 (edition 2024) engineer. It builds Cargo workspaces with shared lints, thiserror/anyhow, tokio + axum + sqlx services, and a clap CLI, with proptest and criterion tests. The gate is clippy, cargo-deny, and cargo-machete, and it ships lean distroless deploys with Kamal. It bundles an audit script and a workspace scaffolder. |
| [`zig`](skills/zig/SKILL.md) | An opinionated Zig 0.16 engineer. It covers build.zig and build.zig.zon, explicit allocators, error unions, comptime, the new `std.Io` interfaces, `std.http` services, C and WASM interop, and musl cross-compilation. Its audit catches APIs removed in recent releases that agents often hallucinate, and it bundles a scaffolder. |
| [`c`](skills/c/SKILL.md) | An opinionated modern C (C23) engineer. It uses CMake presets, strict warnings, ASan/UBSan/TSan, OpenSSF hardening (with platform guards), opaque types, ownership conventions, arenas, checked arithmetic, CTest, libFuzzer, and static musl builds via `zig cc`. It bundles an audit script and a scaffolder. |
| [`cpp`](skills/cpp/SKILL.md) | An opinionated modern C++23 engineer. It uses CMake presets, vcpkg manifests with a pinned baseline, RAII and the Rule of Zero, `std::expected`, jthread, clang-tidy, sanitizers, library hardening modes, GoogleTest via CTest, and fuzzing. It deploys mostly-static binaries on distroless with Kamal, and bundles an audit script and a scaffolder. |
| [`shape-up`](skills/shape-up/SKILL.md) | Acts as an expert practitioner of Basecamp's [Shape Up](https://basecamp.com/shapeup) method. It shapes raw ideas into pitches (appetite, breadboards, rabbit holes, no-gos), runs betting tables, hands projects to teams, maps scopes, reads hill charts, and hammers scope to ship on time. It bundles a pitch checker and a hill-chart renderer. |
| [`bun-elysia`](skills/bun-elysia/SKILL.md) | An opinionated senior Bun + Elysia engineer. It builds type-safe TypeScript monorepos with Bun workspaces and catalogs, Elysia feature modules with framework-blind services, Eden Treaty end-to-end types for Next.js and Expo, Drizzle on Bun SQL, pg-boss jobs, Better Auth, bun test, Biome, and compiled-binary deploys with Kamal behind Cloudflare. Its templates are verified together (they lint, type-check, test, and compile), and it bundles a repo audit and a module scaffolder. |
| [`php-laravel`](skills/php-laravel/SKILL.md) | An opinionated senior PHP 8.5 + Laravel 13 engineer. It builds the Laravel way with final readonly Actions, Form Requests, policies, and API resources, Eloquent in strict mode on PostgreSQL, database queues then Redis + Horizon, Livewire 4 (or Inertia 3), Filament, Sanctum, and Reverb. The gate is Pest 5 with arch tests, Larastan at level max, Pint, and Rector, and it deploys FrankenPHP + Octane containers with Kamal behind Cloudflare (or Laravel Cloud). It ships iOS and Android apps with NativePHP, and bundles an app audit and a resource scaffolder. |
| [`python`](skills/python/SKILL.md) | An opinionated Python 3.14 engineer. It uses uv projects and workspaces, the `src/` layout, ruff (`extend-select`), strict mypy, and typed dataclasses and pydantic at the boundaries. Services are FastAPI + async SQLAlchemy + Alembic + psycopg 3 with procrastinate Postgres jobs, tested with pytest + hypothesis against a real Postgres, and deployed as slim uv-built containers with Kamal. It bundles an ast-based audit and a scaffolder. |
| [`typescript`](skills/typescript/SKILL.md) | An opinionated TypeScript 7 engineer. It uses a strict, erasable-syntax tsconfig, discriminated unions and branded types, Zod 4 at the boundaries, and AbortSignal-first async. The gate is Biome plus oxlint type-aware linting (typescript-eslint doesn't support TS 7). It tests with Vitest and `expectTypeOf`, publishes with tsdown + publint + attw, and runs Hono services on Node 24 or Bun. It bundles an audit that runs on both Node and Bun, and defers Bun + Elysia backends to `bun-elysia`. |
| [`ruby-on-rails`](skills/ruby-on-rails/SKILL.md) | An opinionated senior Ruby and Rails 8 engineer. It builds a modular majestic monolith: DDD bounded contexts in `app/domains` enforced by Packwerk, operation, form, and query objects, Hotwire + ViewComponent + Tailwind, the Solid stack, PostgreSQL/PgBouncer, RSpec + FactoryBot, Pundit, and Kamal behind Cloudflare. It ships iOS and Android apps with Hotwire Native, and bundles an app audit and a path-configuration validator. |

## Install

**Any agent, via the [`skills`](https://github.com/vercel-labs/skills) CLI:**

```bash
npx skills add ar4mirez/skills --list              # see what's available
npx skills add ar4mirez/skills --skill shape-up    # install one skill into this project
npx skills add ar4mirez/skills --skill shape-up -g # install globally, for all projects
```

**Claude Code, as a plugin marketplace:**

```
/plugin marketplace add ar4mirez/skills
/plugin install shape-up@ar4mirez-skills
```

**Manually:** copy or symlink `skills/<name>/` into your agent's skills
directory, for example `~/.claude/skills/<name>` or `.agents/skills/<name>`.
Each skill directory is self-contained.

## Development

Requirements: Python 3.9+ and `make`. Optionally, install
[`skills-ref`](https://github.com/agentskills/agentskills/tree/main/skills-ref)
for the reference validator.

```bash
make help                              # list targets
make new name=my-skill desc="One line" # scaffold from template/ and register it in the marketplace
make check                             # validate every skill and run script tests (what CI runs)
make validate-ref                      # run the official skills-ref validator too
make link                              # symlink skills into ~/.claude/skills for live local testing
```

See [AGENTS.md](AGENTS.md) for the authoring rules and the evaluation workflow.
CI runs the same checks on every push and pull request.

## Repository layout

```
skills/<name>/            installable skill: SKILL.md + references/ assets/ scripts/ evals/
template/                 skeleton for new skills
scripts/                  repo tooling (validate_skills.py, new-skill.sh, link-local.sh)
tests/                    tests for scripts bundled inside skills
.claude-plugin/           Claude Code marketplace manifest (one plugin per skill)
.github/workflows/        CI: spec validation, skills-ref, tests
```

## Acknowledgements

The `shape-up` skill paraphrases and cites *Shape Up: Stop Running in Circles
and Ship Work that Matters* by Ryan Singer, © Basecamp, which is freely
available at https://basecamp.com/shapeup. This repository isn't affiliated
with or endorsed by Basecamp or 37signals. Read the book, because it's
excellent.

## License

[MIT](LICENSE)
