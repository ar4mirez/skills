# Testing

**The rule: test the contract, at the level the user touches it.** Most
tests are Pest feature tests hitting routes and Livewire components against
a real database. Unit tests cover tricky actions and value logic. Arch tests
guard the conventions. Every template here passes on SQLite and on
Postgres 18.

## Contents
- Setup
- What to test, at which level
- Feature tests (HTTP and APIs)
- Livewire tests
- Actions and unit tests
- Jobs, events, mail, and HTTP fakes
- Factories
- Arch tests
- Browser tests
- Speed: parallel, lazy refresh, type coverage
- CI gate

## Setup

`tests/Pest.php` (`assets/Pest.php`):

```php
pest()->extend(TestCase::class)
    ->use(LazilyRefreshDatabase::class)
    ->beforeEach(function (): void {
        Http::preventStrayRequests();   // an unfaked HTTP call fails the test
        $this->withoutVite();           // no "Vite manifest not found" in view tests
    })
    ->in('Feature', 'Unit');
```

- `LazilyRefreshDatabase` migrates once and wraps each test in a
  transaction, but only for tests that touch the database.
- The skeleton's `phpunit.xml` uses SQLite `:memory:`, which is fast for
  local runs. **CI runs against Postgres** (drop the `DB_CONNECTION` /
  `DB_DATABASE` env lines and set `DB_*` from the service). SQLite hides
  locking, JSON, and case-sensitivity differences.
- Pest 5 needs PHP ≥ 8.4.

## What to test, at which level

| Level | For | Example |
|---|---|---|
| Feature (HTTP) | Every endpoint: auth, validation, tenant isolation, the response shape | `InvoiceApiTest.php` |
| Feature (Livewire) | Every page component's behavior and authorization | `InvoicesPageTest.php` |
| Feature (jobs, commands) | Idempotency, side effects | `SendInvoiceReminderTest.php` |
| Unit | Actions with branching rules, enums, value objects | `RecordPaymentTest` |
| Arch | Layering and conventions | `ArchTest.php` |
| Browser | A handful of critical journeys (sign-up, checkout) | `pest-plugin-browser` |

Don't test the framework (that `hasMany` works, that validation rule
`required` rejects null). Test *your* rules through the endpoint.

## Feature tests (HTTP and APIs)

```php
it('forbids reading another account\'s invoice', function (): void {
    Sanctum::actingAs(User::factory()->create());

    getJson('/api/invoices/'.Invoice::factory()->create()->id)->assertForbidden();
});

it('validates the payload', function (array $payload, string $field): void {
    Sanctum::actingAs(User::factory()->create());

    postJson('/api/invoices', $payload)->assertUnprocessable()->assertJsonValidationErrors($field);
})->with([
    'missing email' => [['amount_cents' => 100, 'due_on' => '2099-01-01'], 'customer_email'],
    'zero amount' => [['customer_email' => 'a@b.co', 'amount_cents' => 0, 'due_on' => '2099-01-01'], 'amount_cents'],
]);
```

- **Every endpoint gets a tenant-isolation test.** It's the bug with the
  worst blast radius.
- Use datasets (`->with([...])`) for validation matrices.
- Use `assertJsonPath`, `assertJsonCount`, and `assertExactJson` for
  contracts. Import the `Pest\Laravel\getJson` functions or use
  `$this->getJson`.
- `actingAs($user)` for session auth; `Sanctum::actingAs($user, ['abilities'])`
  for tokens.

## Livewire tests

```php
Livewire::actingAs($user)
    ->test('pages::invoices.index')
    ->assertSee('INV-00001')
    ->set('status', 'paid')
    ->assertDontSee('INV-00001');

// tampering: call the action with another tenant's id
Livewire::actingAs(User::factory()->create())
    ->test('pages::invoices.index')
    ->call('markPaid', $foreignInvoice->id)
    ->assertForbidden();
```

Write the tampering test for every action that takes an id.

## Actions and unit tests

- Resolve actions from the container (`resolve(RecordPayment::class)`) so
  their dependencies are real, or swap one with `$this->mock()` /
  `$this->instance()` for an external gateway.
- Assert domain exceptions with `->throws(InvoiceNotPayable::class, 'is draft')`.
- Pure unit tests (no database, no app) for enums and value objects run
  in milliseconds. Put them in `tests/Unit` without the database trait.

## Jobs, events, mail, and HTTP fakes

- `Queue::fake()` + `Queue::assertPushed(SendInvoiceReminder::class)` to
  test that something is dispatched. Run the job itself with
  `SendInvoiceReminder::dispatchSync($invoice)` to test what it does.
- Test idempotency directly: dispatch twice, then assert one side effect
  (`Notification::assertSentOnDemandTimes(..., 1)`).
- `Event::fake([InvoicePaid::class])` fakes only the listed events, so
  model events keep working.
- `Http::fake(['api.stripe.com/*' => Http::response([...], 200)])` plus
  `preventStrayRequests()`. Assert requests with `Http::assertSent(fn ($r) => ...)`.
- Time: `$this->travelTo(now()->addDays(31))`, `freezeTime()`.
- `Str::uuid()` and other `Str` factories reset between tests in
  Laravel 13, so `Str::createUuidsUsing()` doesn't leak.

## Factories

- One factory per model with **valid defaults** and named states for
  meaningful variants (`->sent()`, `->overdue()`, `->paid()`).
- Parents via relations: `'account_id' => Account::factory()`, and
  `->for($user->account)` in tests to share a tenant.
- Keep factories minimal. A factory that creates ten related records by
  default makes every test slow and every failure confusing.
- Seeders are for local/demo data, not tests.

## Arch tests

`assets/ArchTest.php` uses the `php`, `security`, and `laravel` presets plus
house rules (strict types, action shape, thin controllers, models not
using HTTP, no debug calls). Add one rule each time a review comment
repeats. Consider `arch()->preset()->strict()` (final classes, strict
equality, no protected methods in final classes) for greenfield code.

## Browser tests

Pest 5's browser plugin (`pestphp/pest-plugin-browser`, Playwright under
the hood) runs real-browser tests with the same Pest syntax
(`visit('/login')->fill(...)->press(...)->assertSee(...)`), and Livewire has
`Livewire::visit()`. Keep them to critical journeys; they're slow and
flakier than feature tests. Dusk is the older alternative.

## Speed: parallel, lazy refresh, type coverage

- `pest --parallel` (the `composer test` script does this). Each process gets
  its own database (`_test_1`, `_test_2`, ...).
- `LazilyRefreshDatabase`, not `RefreshDatabase`, and no `sleep()`.
- `pest --type-coverage --min=100` fails on any untyped parameter, property,
  or return. It needs about 1 GB of memory on a mid-size app
  (`php -d memory_limit=1G`).
- `pest --profile` finds the slow tests. `--dirty` runs only changed tests
  locally.

## CI gate

`assets/github-ci.yml` runs on a Postgres 18 service:
1. `composer install`, and `.env` + key.
2. `npm ci && npm run build` (views need the manifest outside tests).
3. `composer check`: `validate --strict`, Pint `--test`, Rector
   `--dry-run`, Larastan level max, Pest parallel with type coverage,
   `artisan optimize` + `optimize:clear` (catches route-cache and
   config-cache failures), and `composer audit`.

Zero warnings allowed. A red check blocks the merge.
