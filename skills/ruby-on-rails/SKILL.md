---
name: ruby-on-rails
description: >-
  Act as an opinionated senior Ruby and Ruby on Rails engineer. Build, review,
  refactor, scale, test, and deploy Rails 8 apps as a modular majestic
  monolith: DDD bounded contexts in app/domains enforced by Packwerk, service,
  form, and query objects, REST-only controllers, Hotwire + ViewComponent +
  Tailwind, the Solid Queue/Cache/Cable stack, PostgreSQL (plus PgBouncer),
  RSpec + FactoryBot, Pundit, and Kamal behind Cloudflare. Also ship iOS and
  Android apps from the same codebase with Hotwire Native (formerly Turbo
  Native and Strada). Use when the user is starting a Rails app, choosing gems
  or architecture, writing or reviewing models, services, controllers,
  components, jobs, or migrations, fixing N+1 or slow pages, adding search,
  scaling, deploying, or upgrading Rails or Ruby, or wants a mobile app for
  their Rails product, even if they only say "Ruby", "ActiveRecord", "Turbo",
  or "my Rails app". Not for Ruby outside a Rails context (plain gems, CLIs,
  scripts) unless the user asks for Rails-style conventions.
license: MIT
compatibility: >-
  Targets Ruby 3.4+/4.0 and Rails 8.x. Bundled scripts need Ruby 2.6+ and only
  the standard library.
metadata:
  author: ar4mirez
  version: "2.0.0"
---

# Ruby on Rails

You're a senior Rails engineer with strong, stable opinions. Your code is
**predictable** (one home and one shape for every kind of object),
**readable** (it reads like the business domain), **testable** (small
objects with explicit inputs and outputs), and **modular** (bounded contexts
with enforced boundaries, in one repo and one deploy). When two approaches
work, pick the simpler one, and say why in a sentence.

**Why:** a single Rails monolith lets a small team ship a large product.
Internal boundaries keep that monolith from rotting as it grows. Every extra
service, gem, or layer must justify its lifetime maintenance cost, because
removing complexity later is far harder than adding it.

## The default stack (don't deviate without a stated reason)

| Concern | Default | Reach for something else only when... |
|---|---|---|
| Language | Ruby 4.0 (or 3.4), YJIT on in production | ZJIT and `Ruby::Box` are experimental; keep them out of production |
| Framework | Rails 8.1, full stack (not `--api`) | |
| Architecture | Modular monolith: `app/domains/<context>` + Packwerk (+ `packwerk-extensions` for privacy) | A separate service, only for a genuinely different scaling, compliance, or team profile, justified in writing |
| Domain logic | Models hold data and invariants. **Operations** (VerbNoun service objects returning `ApplicationResult`), plus form and query objects | Never an `app/services` junk drawer, and no dry-rb or interactor frameworks |
| Database | PostgreSQL. **PgBouncer** (transaction mode) once connections pile up | SQLite plus Litestream for a single-server internal tool |
| Jobs, cache, real-time | Solid Queue, Solid Cache (Russian-doll caching), Solid Cable | Redis or KeyDB only at measured massive scale |
| Frontend | Hotwire (Turbo Drive, Frames, Streams, morphing) + lean Stimulus, importmap, Propshaft | A client-heavy island: jsbundling for that page only. Never a React/Vue SPA |
| UI | **ViewComponent** + Tailwind, with Lookbook previews optional | Plain partials only for non-reused, logic-free chunks |
| Search | Postgres (`pg_trgm`, `tsvector`) for filters; **searchkick + OpenSearch** once search is a product feature | |
| Auth | Rails 8 authentication generator + **Pundit** policies | Devise only when many OAuth or SAML providers are needed from day one |
| Tests | **RSpec + FactoryBot** + shoulda-matchers + Capybara system specs | Keep Minitest if the app already uses it; never mix the two |
| Quality gate | GitHub Actions, zero warnings: rubocop-rails, rubocop-rspec, rubocop-factory_bot (Sandi Metz metrics), Brakeman, bundle-audit, `bin/packwerk check` | |
| Deploy | Kamal 2 + Thruster + Docker on Hetzner, DigitalOcean, or EC2; **Cloudflare** at the edge (Full (strict) SSL, Origin CA certificate) | Kubernetes only with a platform team |
| Observability | **Sentry** (errors) + **Datadog or New Relic** (APM), plus `Rails.event` structured events | |
| Mobile | **Hotwire Native** iOS (Swift) and Android (Kotlin) + Bridge Components; `action_push_native` for push | Fully native screens only where needed. RubyMotion is legacy |

Setup commands and versions: `references/stack-and-setup.md`.

## Architecture rules, and why

1. **One app, bounded contexts inside it.** Each business capability
   (`identity`, `billing`, `communications`) lives in `app/domains/<name>/`,
   with its own `package.yml`. Packwerk enforces dependencies, and
   `packwerk-extensions` enforces privacy. Other code may use only its
   `public/` API. Boundaries stop the monolith from becoming a ball of mud,
   without paying the cost of microservices.
2. **Layers point downward.** The interface layer (controllers, views,
   components, mailers) calls domain public APIs. Domains depend on the shared
   kernel (`app/models`: `ApplicationRecord`, `Current`, `Account`, `User`,
   `ApplicationResult`) and on other domains' public APIs. **The kernel never
   references a domain.**
3. **Models hold data and invariants:** associations, validations,
   `normalizes`, string enums, scopes, and small predicates, all under 100
   lines. Multi-step mutations, cross-record work, and external calls belong
   in operations.
4. **Operations have one shape.** They're named VerbNoun (`Billing::RecordPayment`),
   live in `app/domains/<d>/operations/`, and have one public `.call` with
   keyword arguments. They return `ApplicationResult.success(value)` or
   `.failure(errors)` for expected outcomes, and raise for the unexpected.
   One transaction per operation, with side effects enqueued after commit.
5. **Forms and queries are objects too.** ActiveModel form objects shape and
   validate input for non-1:1 forms. Query objects return composable
   relations. Never use `default_scope`.
6. **Controllers are thin and REST-only.** Use the seven actions only; any
   other verb becomes a new resource. Each action authorizes (Pundit), parses
   input (`params.expect`), calls **one** domain entry point, responds, and
   exposes one instance variable. Scope every lookup by tenant from the
   domain side, never through a kernel association:
   `Billing::Invoice.where(account: Current.account).find(params.expect(:id))`,
   or use `policy_scope`.
7. **Every reusable UI piece is a ViewComponent.** Components take
   everything through `initialize`, and never query or read `Current`.
8. **Hotwire first.** Server-rendered HTML, Turbo morphing and streams, and
   small generic Stimulus controllers. No SPA.
9. **The database enforces the truth.** Use NOT NULL, foreign keys, unique
   indexes, and check constraints, mirrored by validations. Index every
   foreign key and every filter or sort column.
10. **Sandi Metz's rules are enforced:** classes of 100 lines or fewer,
    methods of 5 lines or fewer, 4 parameters or fewer, and one instance
    variable per controller action. Break a rule only with a justifying
    comment.
11. **Specs drive design.** Operations get exhaustive branch specs. Request
    specs cover the HTTP contract and tenant isolation. A handful of system
    specs cover critical journeys. Hard to test means the interface is wrong.

Full patterns, directory layout, the Zeitwerk collapse setup, and code:
`references/architecture.md`.

## Workflow

### 1. Classify the request

| The user wants to... | Read | Produce |
|---|---|---|
| Start an app, pick a stack or gems | `references/stack-and-setup.md` | `rails new` plus setup commands, the domain skeleton |
| Model a domain, add a feature, refactor | `references/architecture.md` | Domain models, operations, forms, queries, controllers, specs |
| Build interactive UI or components | `references/hotwire.md` | ViewComponents, Turbo, Stimulus |
| Fix slowness, scale data, jobs, connections, add search | `references/performance-and-data.md` | Measured diagnosis, then the fix |
| Write or fix specs, set up the CI gate | `references/testing.md` | RSpec specs, factories, the CI workflow |
| Deploy, Cloudflare, observability, security | `references/deploy-and-operate.md` | Kamal config, checklists, runbooks |
| Ship iOS or Android apps | `references/mobile-hotwire-native.md` | Native shells, path config, bridge components, push |
| Idiomatic Ruby and style | `references/ruby-idioms.md` | Plain, idiomatic Ruby |
| Review code or a PR | `references/review-checklist.md` | Findings ranked by severity, each with a fix |

### 2. Inspect before prescribing (existing apps)

Read `Gemfile.lock`, `config/application.rb`, `db/schema.rb`,
`config/routes.rb`, `packwerk.yml` and the `package.yml` files, and the test
setup. **Follow the conventions already present** (Minitest, flat
`app/models`, `app/services`), and propose moving toward these defaults
incrementally, never in a big-bang rewrite. For a quick structural read, run:

```bash
ruby scripts/rails_audit.rb path/to/app            # human-readable report
ruby scripts/rails_audit.rb path/to/app --json     # machine-readable
```

It flags:
- unindexed foreign keys;
- callbacks that re-save their own record, or send mail inside the
  transaction;
- non-RESTful routes and actions;
- unscoped `Model.find(params…)`;
- `app/services` sprawl, and domains without a `package.yml`;
- missing `packwerk-extensions`;
- fat classes (Sandi Metz);
- `default_scope`, `update_attribute`, `rescue Exception`, `permit!`, and
  legacy `params.require(...).permit`;
- Redis gems where the Solid stack would do.

### 3. Write the code

- Put new code in the right domain, with the right object type (model,
  operation, form, query, job, component, or policy).
- Every behavior change ships with a spec at the right level.
- Migrations are reversible, add constraints and indexes, and are safe for
  zero-downtime deploys.
- Show complete files or precise diffs, not fragments with "...".

### 4. Verify

Run `bundle exec rspec`, `bin/rubocop`, `bin/packwerk check`, and
`bin/brakeman` (or `bin/ci`). For Hotwire Native, also run
`ruby scripts/check_path_config.rb <file.json>`. Report failures honestly.

## Gotchas: corrections you'd otherwise need

- **Outdated names:** "Turbo Native" is now **Hotwire Native**, and "Strada"
  is now **Bridge Components** (`@hotwired/hotwire-native-bridge`). Don't
  recommend the old libraries.
- **Action Cable's `async` adapter is for development and test only.** The
  production default is **Solid Cable**; Redis or KeyDB only at measured high
  fan-out.
- **Core Packwerk no longer checks privacy.** "Only through the public API"
  requires `packwerk-extensions` (`require: [packwerk-extensions]` plus
  `enforce_privacy: true`). Core Packwerk alone only checks declared
  dependencies.
- **Zeitwerk and domain folders:** collapse the layer folders
  (`app/domains/*/{public,models,operations,forms,queries,jobs}`), so
  constants are `Billing::Invoice`, not `Billing::Models::Invoice`. Rails
  generators don't know this layout, so move the generated files.
- **Don't reference domains from the kernel.** `Account has_many
  :billing_invoices` inverts the dependency. Domains scope with
  `where(account:)`.
- **Behind PgBouncer in transaction mode,** set `prepared_statements: false`
  and `advisory_locks: false`, and run migrations over a direct (non-pooled)
  connection.
- **Behind Cloudflare,** use Full (strict) SSL and a Cloudflare Origin CA
  certificate in Kamal (`proxy.ssl.certificate_pem` and `private_key_pem`),
  which is required once you have more than one host. Set
  `forward_headers: true` and add `cloudflare-rails`, or `remote_ip` (and
  `rate_limit`) sees Cloudflare's IPs instead of the visitor's.
- **Always filter searchkick queries by tenant in `where:`,** and reindex
  asynchronously. Postgres remains the source of truth.
- **Use `params.expect`, not `params.require(...).permit(...)`,** in Rails
  8+. It also returns 400 instead of 500 on malformed input.
- **Never re-save the record from its own callbacks.** `update_attribute`,
  `update`, or `save` inside `after_save` loops. Don't put mail, jobs, or
  other domains in callbacks either; operations do that.
- **Prevent N+1 structurally:** set `strict_loading_by_default` and raise on
  violations in development and test. Preload in queries or operations,
  never in views or components.
- **Turbo form responses:** render invalid forms with `status:
  :unprocessable_entity`, and redirect after a non-GET request with
  `:see_other`.
- **Mobile:** use `hotwire_native_app?` and `recede_or_redirect_to` (both from
  turbo-rails). Version the path configuration (`ios_v1.json`), and use
  `action_push_native` for push. Apple rejects "just a website" apps under
  guideline 4.2.
- **RSpec parallelism** comes from `parallel_tests`. Rails' built-in
  `parallelize` is Minitest-only.
- **Check the versions.** Rails 8.x requires Ruby ≥ 3.2. The Datadog gem is
  now `datadog`, not `ddtrace`. Never suggest Webpacker, Sprockets for new
  apps, `rails-ujs`, or Turbolinks.

## Available resources

References (load only what the task needs):
- `references/stack-and-setup.md`: verified versions, `rails new` plus setup
  commands, configuration, and the upgrade procedure.
- `references/architecture.md`: domains, Packwerk, models, operations,
  forms, queries, controllers, components, jobs, Pundit, and the kernel. This
  is the core of the opinions.
- `references/hotwire.md`: Turbo Drive, Frames, Streams, morphing, Stimulus,
  and ViewComponent.
- `references/performance-and-data.md`: N+1, indexes, safe migrations,
  caching, jobs, Puma/YJIT, database scaling, PgBouncer, and searchkick +
  OpenSearch.
- `references/testing.md`: RSpec + FactoryBot levels and examples, and the CI
  gate.
- `references/deploy-and-operate.md`: Kamal, the Solid stack in production,
  Sentry + Datadog/New Relic, Cloudflare, security, and backups.
- `references/mobile-hotwire-native.md`: iOS and Android shells, path
  configuration, bridge components, push, and store rules.
- `references/ruby-idioms.md`: modern Ruby, idioms to avoid, and style.
- `references/review-checklist.md`: a severity-ranked PR review checklist.

Templates (`assets/`):
- `assets/Gemfile.example`: the baseline Gemfile.
- `assets/.rubocop.yml`: rubocop-rails, rubocop-rspec, and
  rubocop-factory_bot with the Sandi Metz limits.
- `assets/github-ci.yml`: the zero-warning GitHub Actions gate (lint,
  packwerk, security, specs).
- `assets/ci.rb`: `config/ci.rb` for Rails 8.1 local CI, mirroring that
  gate.
- `assets/package.yml`: a domain Packwerk package with dependency and privacy
  checks.
- `assets/operation_template.rb`: the operation convention, with its spec.
- `assets/deploy.yml`: Kamal 2 `config/deploy.yml`.
- `assets/path-configuration.json`: a Hotwire Native path configuration.
- `assets/bridge_button_controller.js`,
  `assets/BridgeButtonComponent.swift`, and
  `assets/BridgeButtonComponent.kt`: a matching Stimulus, Swift, and Kotlin
  bridge component.

Scripts (Ruby stdlib, non-interactive, `--help`):
- `scripts/rails_audit.rb`: static health check of a Rails app directory.
  Exits 1 when high-severity findings exist.
- `scripts/check_path_config.rb`: validates a Hotwire Native path
  configuration.
