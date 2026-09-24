# Rails code review checklist

Report findings **ranked by severity**. Give each one a file and line, what's
wrong, why it matters, and the concrete fix (code).

## Critical: security and data integrity

- [ ] **Unscoped lookup:** `Invoice.find(params[:id])` instead of
      `Current.account.invoices.find(...)`. That's an IDOR vulnerability.
- [ ] Mass assignment: `permit!`, or permitting `role`, `account_id`, or
      `admin`.
- [ ] SQL injection: string interpolation in `where`, `order`, or `pluck`
      with user input.
- [ ] XSS: `html_safe`, `raw`, or `<%==` on user content.
- [ ] A side effect inside the transaction: email or HTTP in `after_save`, or
      a job enqueued before commit on old configurations.
- [ ] A migration that locks a big table (an index without `concurrently`),
      renames or removes a column in one deploy, or backfills in the
      migration.
- [ ] Missing unique index behind a `uniqueness` validation. Missing foreign
      key or `null: false` on required associations.
- [ ] Secrets in code or logs, or missing `filter_parameters`.

## High: correctness and performance

- [ ] N+1: association access in views or loops without preloading.
- [ ] Unbounded queries: `.all` in a request, `each` over large tables
      (`find_each`), or missing pagination.
- [ ] Missing index for new `where` or `order` columns, or for foreign keys.
- [ ] Non-idempotent jobs, or passing full objects or large payloads instead
      of ids.
- [ ] Rescuing broadly (`rescue => e` then nothing, `rescue Exception`).
- [ ] Time-zone bugs: `Date.today` or `Time.now` instead of `Date.current` or
      `Time.current`.
- [ ] Order-dependent `first` or `last` without `order` (deprecated in 8.1).
- [ ] Turbo form responses without `status: :unprocessable_entity`, or
      redirects without `:see_other`.

## Medium: design

- [ ] Non-RESTful controller actions: extract a resource controller.
- [ ] Business logic in controllers, views, helpers, or jobs: move it to the
      model or a PORO.
- [ ] A new `app/services/*Service`: rename it to a domain PORO under
      `app/models`, or put it on the model.
- [ ] Callbacks doing cross-aggregate work: make them explicit methods.
- [ ] `default_scope`, `update_attribute` or `update_column` bypassing
      validations without comment, or boolean flags where a timestamp would
      tell more.
- [ ] Concerns that are grab-bags, or that reach into one host's private
      internals.
- [ ] New gems that the framework already covers (Redis, Sidekiq, Devise,
      service-object frameworks).
- [ ] Hand-written Turbo Streams where `broadcasts_refreshes` plus morphing
      would do.

## Low: tests and style

- [ ] Behavior change without a test at the right level, or tests that assert
      framework behavior.
- [ ] Factories and fixtures bloat; `sleep` in system tests.
- [ ] Naming doesn't match the domain language, or methods over about 10
      lines.
- [ ] RuboCop omakase violations (let the tool report these; don't
      hand-review style).

Run `ruby scripts/rails_audit.rb <app>` for the structural checks it can
detect, then review the diff for the rest.
