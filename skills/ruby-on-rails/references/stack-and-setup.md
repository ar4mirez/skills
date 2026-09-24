# Stack and setup

Versions were verified against RubyGems and ruby-lang.org in September 2026.
Always check `Gemfile.lock` in an existing app, and prefer the latest patch
release of these versions for new ones.

## Current versions

| Component | Version | Notes |
|---|---|---|
| Ruby | 4.0.x (4.0.7); 3.4.x is still fine | Ruby 4.0 (Dec 2025) added ZJIT (experimental), `Ruby::Box` (experimental, `RUBY_BOX=1`), and a reworked Ractor API. Use YJIT in production. |
| Rails | 8.1.x (8.1.4) | 8.1 adds Active Job continuations, `Rails.event` structured events, local CI (`config/ci.rb` + `bin/ci`), Markdown rendering, deprecated associations, `rails credentials:fetch`, and registry-free Kamal deploys. It requires Ruby ≥ 3.2. |
| Rails 8.0 features | | Kamal 2, Thruster, Solid Cache/Queue/Cable, Propshaft by default, the authentication generator, `params.expect` |
| turbo-rails / stimulus-rails | 2.0.x / 1.3.x | Turbo 8: morphing page refreshes, `hotwire_native_app?` |
| solid_queue / solid_cache / solid_cable | 1.7 / 1.0 / 4.0 | Database-backed; no Redis |
| kamal / thruster | 2.12 / 0.1.x | |
| propshaft / importmap-rails / tailwindcss-rails | 1.3 / 2.2 / 4.x (Tailwind v4) | |
| Hotwire Native | iOS 1.3.x, Android 1.3.x | Swift Package `hotwire-native-ios`; Gradle `dev.hotwire:core` and `dev.hotwire:navigation-fragments` |
| Supporting gems | rubocop-rails-omakase 1.1, brakeman 8, bundler-audit 0.9, pagy 43, mission_control-jobs 1.3, view_component 4, pundit 2.5, strong_migrations 2.8, prosopite 2.2, rack-mini-profiler 5 | |

## New app

```bash
# Multi-server, or anything with growth ahead:
rails new acme --database=postgresql --css=tailwind

# Single-server product or internal tool (SQLite is production-grade in Rails 8):
rails new acme --css=tailwind

cd acme
bin/rails generate authentication
bin/setup
bin/dev
```

Leave these defaults alone: importmap, Propshaft, Solid Queue/Cache/Cable,
Kamal, Thruster, Minitest, `rubocop-rails-omakase`, Brakeman, and the GitHub
CI workflow.

Change a default only for a specific reason:

| Flag | Use it only when... |
|---|---|
| `--javascript=esbuild` or `bun` | You need npm packages that don't work through importmap, like a rich-text editor or a charting library with a build step |
| `--api` | The app is purely a JSON backend for existing native or SPA clients. With Hotwire Native, keep the full app |
| `-T` (skip Minitest) | Only if the team is committed to RSpec. Then add rspec-rails and factory_bot_rails |

## Baseline Gemfile additions

See `assets/Gemfile.example` for the full file. Add these on top of the
`rails new` defaults:

```ruby
gem "pagy"                       # pagination: fast, no model pollution
gem "mission_control-jobs"       # Solid Queue dashboard (mount behind auth)
gem "strong_migrations"          # blocks unsafe migrations (Postgres/MySQL apps)

group :development do
  gem "rack-mini-profiler"       # always-on profiling badge in development
end

group :development, :test do
  gem "prosopite"                # N+1 detection (or rely on strict_loading)
end
```

Don't add these by default: `devise` (use the generator), `sidekiq` and
`redis` (use the Solid stack), `dry-*`, `interactor`, `trailblazer`,
`draper`, `aasm` (enums plus methods cover most state), `paranoia` or
`discard` (use a `Trashable` concern), and `annotate` (read `schema.rb`).

## Configuration worth setting

```ruby
# config/application.rb
config.active_record.strict_loading_by_default = true   # lazy loads raise or log (see below)
config.active_job.queue_adapter = :solid_queue          # already the default in production

# config/environments/development.rb and test.rb
config.active_record.action_on_strict_loading_violation = :raise
config.i18n.raise_on_missing_translations = true
config.action_dispatch.verbose_redirect_logs = true     # Rails 8.1

# config/environments/production.rb
config.active_record.action_on_strict_loading_violation = :log
config.solid_queue.connects_to = { database: { writing: :queue } }  # generated default
```

- YJIT is enabled automatically by Rails (7.2+) on Ruby versions that support
  it. Keep it on. Set `config.yjit = false` only to debug.
- Keep `config.active_job.enqueue_after_transaction_commit` at its default
  (true in modern apps).
- Put secrets in encrypted credentials per environment
  (`bin/rails credentials:edit --environment production`). Use `ENV` only for
  values that differ between deployments of the same environment.

## Upgrading Rails or Ruby (procedure)

1. Get the suite green, and add system tests for critical paths if they're
   missing.
2. Upgrade one minor version at a time (7.1 → 7.2 → 8.0 → 8.1). Fix
   deprecation warnings at each step first:
   `config.active_support.deprecation = :raise` in test.
3. `bundle update rails`, then `bin/rails app:update` and review each diff.
   Keep `config.load_defaults` at the old version, then flip the
   `new_framework_defaults_*.rb` settings one by one.
4. Bump `config.load_defaults` last, and delete the initializer.
5. Upgrade Ruby separately from Rails: update `.ruby-version`, the Dockerfile,
   and CI, run the suite, and check native gems.
6. Deploy behind the usual process. Upgrades go out on their own, never
   bundled with features.
