# Review checklist

Rank findings by severity, give each a concrete fix (a code change, not
advice), and cite `file:line`. Run `php scripts/laravel_audit.php <app>` from
this skill first for the structural checks it can detect, then review the
diff for the rest.

## Contents
- High: security and data loss
- High: correctness
- Medium: design
- Medium: performance
- Low: tests and style

## High: security and data loss

- [ ] Mass assignment: `create($request->all())`, `fill($request->input())`,
      `$guarded = []`, `#[Unguarded]`. Fix: `validated()` or a DTO, plus
      `#[Fillable]`.
- [ ] Missing authorization: a controller or Livewire action without a
      policy check, a Form Request `authorize()` returning `true`, or
      "the button is hidden" as the only guard.
- [ ] IDOR: `Model::find($id)` / `findOrFail($request->id)` without tenant
      scoping; `Rule::exists` without the tenant `where`.
- [ ] Livewire actions that take an id and don't re-query and authorize;
      public id properties without `#[Locked]`.
- [ ] SQL built from variables in `whereRaw`, `selectRaw`, `orderByRaw`,
      `DB::select`, or `DB::statement`; unvalidated column names in
      `orderBy`.
- [ ] `{!! !!}` with anything user-controlled; `unserialize` of input;
      `exec` / `shell_exec` with input.
- [ ] CSRF disabled broadly (`except: ['*']`); webhooks without signature
      verification.
- [ ] Secrets in code or in `.env.example`, `env()` outside config,
      `APP_DEBUG=true` outside local, Telescope in production.
- [ ] Uploads stored under the client filename, or public disks for
      private files.
- [ ] Open redirects (`redirect($request->input('next'))`).
- [ ] Destructive migrations (`dropColumn`, `renameColumn`, a type
      `change()`) on live tables without expand/contract.

## High: correctness

- [ ] Side effects inside transactions without after-commit (jobs, events,
      mail, notifications).
- [ ] Non-idempotent jobs: a retry double-charges, double-emails, or
      double-inserts.
- [ ] Read-then-write without `lockForUpdate()` (or an atomic update) where
      concurrency matters (balances, sequences, stock).
- [ ] `lockForUpdate()` on an aggregate query (Postgres rejects it).
- [ ] Duplicate route names (web vs. API), which break `route:cache`.
- [ ] Money in floats; times without zones; `new DateTime()` instead of
      `now()`.
- [ ] `Model::automaticallyEagerLoadRelationships()` enabled together with
      strict mode (it silently disables the N+1 guard).
- [ ] Octane: static state or singletons capturing the request, user, or
      config.
- [ ] Unindexed foreign keys on Postgres; uniqueness enforced only by
      validation.

## Medium: design

- [ ] Business logic in controllers, Livewire components, models, jobs, or
      commands: move it into an Action (`app/Actions/<Context>/VerbNoun`,
      `final readonly`, `handle()`).
- [ ] `app/Services/*Service` god classes: split into VerbNoun actions.
- [ ] Non-resource controller methods: extract a resource controller.
- [ ] Inline validation (`$request->validate`) instead of a Form Request.
- [ ] Models returned directly from APIs (no Resource), or resources that
      lazy-load (`whenLoaded` missing).
- [ ] Model events or observers running workflows (mail, other models,
      HTTP).
- [ ] New packages the framework already covers (repositories over
      Eloquent, action frameworks, module packages, DTO frameworks for
      plain DTOs).
- [ ] Global scopes as the *only* tenant guard.
- [ ] Contexts reaching into another context's models once modules
      exist; arch test missing for the rule.

## Medium: performance

- [ ] N+1 (lazy loads in loops, views, or resources), counting in PHP, and
      `Model::all()` or unpaginated `get()` on user-facing lists.
- [ ] Slow work in the request (email, PDFs, API calls, embeddings) that
      belongs in a queue.
- [ ] Missing composite indexes for the actual filters and sorts.
- [ ] Caching without an invalidation story, or caching over an unfixed
      slow query.
- [ ] Big public properties in Livewire components, or whole models in
      Inertia props.

## Low: tests and style

- [ ] A behavior change without a Pest test at the right level; no
      tenant-isolation test for a new endpoint; no tampering test for a
      Livewire action.
- [ ] `Http::fake` without `preventStrayRequests`; `sleep` in tests;
      SQLite-only CI.
- [ ] Missing `declare(strict_types=1)`, untyped parameters or returns
      (type coverage below 100), and non-final classes without a reason.
- [ ] `$casts` property instead of `casts()`, and pipe-string validation
      rules in new code.
- [ ] Pint, Rector, or Larastan failures. Let the tools report style;
      don't hand-review it.
