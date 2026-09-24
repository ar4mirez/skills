# Architecture

The house architecture is **the Laravel default layout plus Actions**, with
Pest arch tests making the conventions enforceable. Every class type has
one home and one shape. All code here matches the verified files in
`assets/`.

## Contents
- Layout
- The request path
- Actions
- Form Requests and DTOs
- Models
- Policies and authorization
- Resources (output)
- Exceptions
- Events, listeners, and jobs
- Service providers and the container
- Enforcing it: arch tests
- Growing into modules

## Layout

```
app/
  Actions/<Context>/VerbNoun.php     business operations (final readonly, handle())
  Data/                              readonly DTOs passed into actions
  Enums/                             backed enums (statuses, types)
  Events/  Listeners/  Jobs/  Notifications/  Mail/
  Exceptions/                        named domain exceptions that render themselves
  Http/
    Controllers/ (+ Api/)            thin, resourceful controllers
    Requests/<Context>/              Form Requests
    Resources/                       API resources
    Middleware/
  Models/                            Eloquent models (data, casts, scopes, relations)
  Policies/                          one per model, auto-discovered
  Providers/AppServiceProvider.php   strictness, rate limits, bindings
resources/views/
  components/                        Blade and Livewire components
  pages/                             Livewire page components (Route::livewire)
routes/web.php  routes/api.php  routes/console.php
tests/Feature  tests/Unit  tests/ArchTest.php
```

Contexts (`Billing`, `Catalog`, `Identity`) appear as sub-namespaces of
Actions and Requests first. That's usually enough for years.

## The request path

```
Route → Controller (or Livewire action)
          ├─ Form Request: authorize() + rules()   → 403 / 422 before your code runs
          ├─ Action::handle(typed input)          → one transaction, domain exceptions
          └─ Resource / redirect / view
```

One entry point per use case, whatever the delivery mechanism: the API
controller, the Livewire page, the console command, and the job all call
`RecordPayment::handle()`.

## Actions

```php
final readonly class RecordPayment
{
    public function handle(Invoice $invoice, int $amountCents): Invoice
    {
        return DB::transaction(function () use ($invoice, $amountCents): Invoice {
            $invoice = Invoice::query()->lockForUpdate()->findOrFail($invoice->id);

            if (! $invoice->status->isPayable()) {
                throw InvoiceNotPayable::because("invoice {$invoice->number} is {$invoice->status->value}");
            }
            // ... mutate, save
            InvoicePaid::dispatch($invoice);   // ShouldDispatchAfterCommit

            return $invoice;
        });
    }
}
```

The rules:
- Name them **VerbNoun** (`CreateInvoice`, `RecordPayment`,
  `CancelSubscription`) under `App\Actions\<Context>`.
- Make them `final readonly`, with collaborators injected through the
  constructor. The container builds them: take them as controller method
  parameters, or call `resolve(RecordPayment::class)`.
- Give them **one public method, `handle()`**, with typed parameters (models,
  enums, DTOs, scalars) and a typed return. There's no `$request`, no
  `request()`, no `auth()` inside, so the same action runs from the API, a
  job, or a test.
- Keep **one transaction per action**. Lock rows you read then write
  (`lockForUpdate()`), and let side effects fire after commit.
- Throw **named domain exceptions** for expected failures
  (`InvoiceNotPayable::because(...)`). Don't return booleans or arrays of
  errors.
- Compose actions by injecting one into another. If you need more than
  two, you probably found a second use case.

`CreateInvoice` shows the pattern for sequences: lock the parent row, then
count, because Postgres refuses `FOR UPDATE` on an aggregate.

## Form Requests and DTOs

```php
final class StoreInvoiceRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()?->can('create', Invoice::class) ?? false;
    }

    public function rules(): array
    {
        return [
            'customer_email' => ['required', 'email:strict', 'max:255'],
            'amount_cents' => ['required', 'integer', 'min:1', 'max:100000000'],
            'due_on' => ['required', 'date', 'after_or_equal:today'],
        ];
    }

    public function toData(): InvoiceData
    {
        return new InvoiceData(
            customerEmail: $this->string('customer_email')->toString(),
            amountCents: $this->integer('amount_cents'),
            currency: $this->string('currency', 'USD')->upper()->toString(),
            dueOn: $this->date('due_on')?->toImmutable() ?? now()->toImmutable(),
        );
    }
}
```

- Put every write endpoint behind a Form Request. `authorize()` returning
  false gives a 403, and failed rules give a 422 (or a redirect with
  errors).
- Use a **`toData()` method returning a `final readonly` DTO** when the
  action takes more than two or three fields. Otherwise pass
  `$request->validated()`. Use typed accessors (`string()`, `integer()`,
  `date()`, `enum()`), never raw `input()`.
- Array rules (`['required', 'integer']`), not pipe strings, so rule objects
  and `Rule::enum()` compose.

## Models

See `eloquent-and-data.md` for the details. The shape:

```php
#[Fillable(['number', 'customer_email', 'amount_cents', 'currency', 'due_on'])]
final class Invoice extends Model
{
    /** @use HasFactory<InvoiceFactory> */
    use HasFactory;

    /** @return BelongsTo<Account, $this> */
    public function account(): BelongsTo { return $this->belongsTo(Account::class); }

    public function isOverdue(): bool { return $this->status->isPayable() && $this->due_on->isPast(); }

    /** @param Builder<self> $query */
    #[Scope]
    protected function overdue(Builder $query): void { /* ... */ }

    protected function casts(): array { return ['status' => InvoiceStatus::class, /* ... */]; }
}
```

- Keep in the model: attributes, casts, relations (with generics for
  Larastan), scopes, and small predicates.
- Move out of the model: workflows, other models' mutations, HTTP, mail,
  and queue dispatches. Those live in actions.
- Avoid model events (`creating`, `saved`, observers) for business
  workflows; they hide control flow. They're fine for derived data on the
  same row (a slug, a normalized email).
- State fields such as `status` never go in `#[Fillable]`. Only actions
  change them, via `forceFill()`.

## Policies and authorization

- One policy per model, auto-discovered (`InvoicePolicy` for `Invoice`).
  Methods follow the resource verbs (`viewAny`, `view`, `create`, `update`,
  `delete`) plus domain verbs (`pay`).
- Authorize in **one** of these places per action: the Form Request's
  `authorize()`, `Gate::authorize('view', $invoice)` in the controller, the
  `#[Authorize('view', 'invoice')]` attribute, or `$this->authorize()` in
  Livewire. Never rely on "the UI hides the button".
- Tenant isolation takes both a scoped query and a policy check. The query
  stops enumeration; the policy stops a bound model from another tenant.
- `Gate::before` only for a super-admin, returning `null` (not `false`)
  for everyone else.

## Resources (output)

- Never return a model from a controller. Use an `InvoiceResource` with
  explicit fields, so adding a column never leaks it.
- Collections use `cursorPaginate()` for APIs (stable under inserts) and
  `paginate()` for UIs that show page numbers.
- For public APIs following the JSON:API spec, use Laravel 13's JSON:API
  resources (see `http-and-api.md`).

## Exceptions

- Domain exceptions extend `DomainException` (or `RuntimeException`), have
  named constructors, and **render themselves** for JSON clients:
  `render(Request $request)` returns a 422 JSON response, or `false` to let
  the framework handle it. See `assets/InvoiceNotPayable.php`.
- Don't catch `Throwable` in controllers. `bootstrap/app.php`'s
  `withExceptions()` is the one place for reporting and rendering rules.

## Events, listeners, and jobs

- **Events** announce facts (`InvoicePaid`) for fan-out to things the
  action shouldn't know about (receipts, analytics, webhooks). Make them
  `ShouldDispatchAfterCommit` when fired inside a transaction.
- **Listeners** are auto-discovered from `app/Listeners` by their
  `handle(EventType $event)` signature. Queue them (`ShouldQueue`) unless
  they're trivial.
- **Jobs** wrap work that's slow, retryable, or scheduled. The job's
  `handle()` usually calls an action. Details: `queues-and-realtime.md`.

## Service providers and the container

- `AppServiceProvider::boot()` holds the global rules (strict mode, rate
  limiters, `Password::defaults`, `URL::forceHttps`, `Date::use`).
- Bind interfaces only when there are real alternative implementations (a
  payment gateway with a fake). Use `#[Bind]`, `#[Singleton]`, or
  `#[Scoped]` attributes, or explicit bindings in `register()`.
- Under Octane, prefer `scoped()` over `singleton()` for anything touching
  the request, user, or tenant.
- Inject the current user with `#[CurrentUser] User $user` instead of
  `auth()->user()`.

## Enforcing it: arch tests

`assets/ArchTest.php`:

```php
arch()->preset()->php();        // no debugging functions, etc.
arch()->preset()->security();   // no eval, md5, unserialize, ...
arch()->preset()->laravel();    // resourceful controllers, naming, suffixes

arch('app code is strictly typed')->expect('App')->toUseStrictTypes();

arch('actions are final, readonly, and expose handle()')
    ->expect('App\Actions')->toBeFinal()->toBeReadonly()->toHaveMethod('handle');

arch('controllers stay thin')->expect('App\Http\Controllers')->not->toUse([DB::class]);

arch('models never reach into HTTP')->expect('App\Models')->not->toUse(['App\Http']);
```

The Laravel preset fails a controller with a non-resource public method.
That's the rule you want: move the verb to its own controller.

## Growing into modules

Stay flat until there are many contexts, several teams, or real coupling
pain. Then move each context into `app/Domains/<Context>/{Actions,Models,Data,Events,Policies}`
(namespace `App\Domains\Billing\...`, no composer changes needed, since
`App\` already maps to `app/`). Enforce the boundaries with arch tests,
not a module package:

```php
arch('billing only talks to catalog through its actions')
    ->expect('App\Domains\Billing')
    ->not->toUse(['App\Domains\Catalog\Models']);

arch('domains never depend on HTTP')
    ->expect('App\Domains')
    ->not->toUse('App\Http');
```

Keep controllers, requests, resources, and Livewire components in the
standard HTTP and view locations. They're the delivery layer and call into
domains. Tell generators where to write (`php artisan make:model
Domains/Billing/Models/Invoice`), register policies explicitly with
`Gate::policy()` or `#[UsePolicy]`, and point factories at the new
namespace with `#[UseFactory]`.
