# Stack and setup

Versions were verified against RubyGems and ruby-lang.org in September 2026.
Always check `Gemfile.lock` in an existing app, and prefer the latest patch
release of these versions for new ones.

## Current versions

| Component | Version | Notes |
|---|---|---|
| Ruby | 4.0.x (4.0.7); 3.4.x is still fine | Ruby 4.0 (Dec 2025) added ZJIT (experimental), `Ruby::Box` (experimental), and a reworked Ractor API. Use YJIT in production. |
| Rails | 8.1.x (8.1.4) | 8.1 adds Active Job continuations, `Rails.event` structured events, local CI (`config/ci.rb` + `bin/ci`), Markdown rendering, deprecated associations, `rails credentials:fetch`, and registry-free Kamal deploys. It requires Ruby ≥ 3.2. |
| Rails 8.0 features | | Kamal 2, Thruster, Solid Cache/Queue/Cable, Propshaft by default, the authentication generator, `params.expect` |
| Hotwire | turbo-rails 2.0.x, stimulus-rails 1.3.x | Turbo 8 morphing. `hotwire_native_app?` helpers |
| Hotwire Native | iOS 1.3.x, Android 1.3.x | This is the current name for "Turbo Native". "Strada" is now **Bridge Components**, built in |
| Solid stack | solid_queue 1.7, solid_cache 1.0, solid_cable 4.0 | Database-backed, so no Redis |
| Deploy | kamal 2.12, thruster 0.1.x | |
| Views | view_component 4.15, tailwindcss-rails 4.x (Tailwind v4), lookbook 2.3 (optional previews) | |
| Boundaries | packwerk 3.3, packwerk-extensions 0.3 (privacy checker) | |
| Auth | Rails 8 authentication generator, pundit 2.5 | |
| Tests | rspec-rails 8.0, factory_bot_rails 6.5, shoulda-matchers 8.0, capybara 3.40 | |
| Quality | rubocop-rails 2.38, rubocop-rspec 3.10, rubocop-factory_bot 2.28, brakeman 8, bundler-audit 0.9 | |
| Search | searchkick 6.1 + opensearch-ruby 3.4 | |
| Observability | sentry-ruby / sentry-rails 7.0; `datadog` 2.x (formerly `ddtrace`) or newrelic_rpm 10.x | |
| Edge | Cloudflare in front of kamal-proxy; `cloudflare-rails` 7 for correct `remote_ip` | |

## New app

```bash
rails new acme --database=postgresql --css=tailwind --skip-test
cd acme

bin/rails generate authentication                        # Rails 8 session scaffolding
bundle add view_component pundit pagy mission_control-jobs strong_migrations
bundle add rspec-rails factory_bot_rails shoulda-matchers --group=development,test
bundle add packwerk packwerk-extensions --group=development,test
bundle add capybara selenium-webdriver webmock --group=test
bundle add rubocop-rails rubocop-rspec rubocop-factory_bot --group=development --require=false
bundle add sentry-ruby sentry-rails

bin/rails generate rspec:install
bin/rails generate pundit:install
bundle binstubs packwerk && bin/packwerk init
```

Then:
1. Copy `assets/.rubocop.yml`, `assets/github-ci.yml` (to
   `.github/workflows/ci.yml`), and `assets/ci.rb` (to `config/ci.rb`).
2. Create `app/domains/` with the first domain, its `package.yml` (see
   `assets/package.yml`), and the Zeitwerk collapse initializer (see
   `architecture.md`).
3. Add `app/models/application_result.rb`, and a first operation from
   `assets/operation_template.rb`.
4. Mount `MissionControl::Jobs::Engine` at `/jobs`, behind an admin
   constraint.
5. Run `bin/setup`, then `bin/dev`.

Rails defaults you keep: importmap, Propshaft, Solid Queue/Cache/Cable,
Kamal, Thruster, and Brakeman.

Add these only when there's a need:
- **searchkick + OpenSearch,** once search is a real feature (fuzzy matching,
  relevance, autocomplete, facets). Before that, use Postgres (`ILIKE`,
  `pg_trgm`, `tsvector`). See `performance-and-data.md`.
- **PgBouncer,** once connection counts outgrow Postgres (many Puma workers,
  many hosts). See `performance-and-data.md` for the transaction-mode
  settings.
- **Datadog or New Relic APM,** once there's production traffic worth
  profiling. Sentry covers errors from day one.
- **Cloudflare,** once the app is public, for DNS, the CDN, and DDoS
  protection. See `deploy-and-operate.md`.
- **A JS bundler** (`jsbundling-rails` with esbuild), only for a
  client-heavy island that needs npm packages that don't work through
  importmap.

Don't add these: Redis or Sidekiq by reflex (the Solid stack covers them),
Devise (use the generator), `dry-*`, `interactor`, or `trailblazer` (use the
plain operation convention), `draper` (use ViewComponent), `aasm` (enums plus
operations), a React or Vue SPA, or Kubernetes.

## Configuration worth setting

```ruby
# config/application.rb
config.active_record.strict_loading_by_default = true        # lazy loads raise or log
config.generators do |g|
  g.test_framework :rspec, fixtures: false
  g.factory_bot dir: "spec/factories"
  g.helper false
  g.stylesheets false
end

# config/environments/development.rb and test.rb
config.active_record.action_on_strict_loading_violation = :raise
config.i18n.raise_on_missing_translations = true
config.action_dispatch.verbose_redirect_logs = true          # Rails 8.1

# config/environments/production.rb
config.active_record.action_on_strict_loading_violation = :log
```

- YJIT is enabled automatically by Rails 7.2+ where it's supported. Keep it
  on.
- Put secrets in encrypted credentials per environment
  (`bin/rails credentials:edit --environment production`). Use `ENV` only for
  values that differ between deployments of the same environment.

## Upgrading Rails or Ruby (procedure)

1. Get the suite green, and add system specs for critical paths if they're
   missing.
2. Upgrade one minor version at a time (7.1 → 7.2 → 8.0 → 8.1). Fix
   deprecations at each step first
   (`config.active_support.deprecation = :raise` in test).
3. `bundle update rails`, then `bin/rails app:update` and review each diff.
   Keep `config.load_defaults` at the old version, then flip the
   `new_framework_defaults_*.rb` settings one at a time.
4. Bump `config.load_defaults` last, and delete that initializer.
5. Upgrade Ruby separately from Rails: update `.ruby-version`, the
   Dockerfile, and CI.
6. Ship each upgrade as its own deploy, never bundled with features.
