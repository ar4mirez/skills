# HTTP and APIs

## Contents
- Routing
- Controllers
- Validation
- Responses and resources
- JSON:API resources
- Authentication: web, SPA, mobile, third parties
- Rate limiting
- Errors
- Versioning and evolution
- Webhooks in and out

## Routing

- Use `Route::resource()` / `apiResource()` with `->only([...])`. Nest for
  sub-resources: `apiResource('invoices.payments', InvoicePaymentController::class)->only(['store'])`
  gives `POST /invoices/{invoice}/payments`.
- **Name API routes with a prefix:** `Route::name('api.')->middleware([...])->group(...)`.
  A web `invoices.index` and an API `invoices.index` pass all tests but make
  `php artisan route:cache` (part of `optimize`) throw at deploy.
- Group by middleware: `auth` (web) or `auth:sanctum` (API), plus `verified`
  and `throttle:api`.
- Bind models implicitly (`{invoice}`), use `scopeBindings()` for nested
  routes so `/accounts/{account}/invoices/{invoice}` checks ownership, and
  `->withTrashed()` only on purpose.
- Keep closures to static pages (`Route::view`). Everything else goes to a
  controller, so it's testable, cacheable, and visible in `route:list`.
- Livewire pages: `Route::livewire('/invoices', 'pages::invoices.index')`.

## Controllers

```php
final class InvoicePaymentController extends Controller
{
    public function store(RecordPaymentRequest $request, Invoice $invoice, RecordPayment $recordPayment): InvoiceResource
    {
        return InvoiceResource::make($recordPayment->handle($invoice, $request->integer('amount_cents')));
    }
}
```

- Use resource methods only (the Pest Laravel arch preset enforces it). A
  new verb means a new controller, or `__invoke` for a single-action
  controller.
- Inject the action as a method parameter and the user with
  `#[CurrentUser] User $user`.
- Declare middleware and authorization with attributes when it reads
  better: `#[Middleware('subscribed')]`, `#[Authorize('update', 'invoice')]`.
- No `DB::`, no query building beyond one scoped read, and no
  `$request->validate()` in controllers.

## Validation

- Use Form Requests (see `architecture.md`), with array-style rules and
  rule objects: `Rule::enum(InvoiceStatus::class)`,
  `Rule::unique('invoices')->where('account_id', $accountId)`,
  `Rule::exists('customers', 'id')->where('account_id', $accountId)`, so
  ids from another tenant fail validation.
- Use `email:strict` (or `email:rfc,dns` for sign-ups), and `Password::defaults()`
  from the provider.
- `prepareForValidation()` normalizes input, such as lowercasing emails.
  Middleware already trims strings and turns empty strings into null.
  `after()` hooks handle cross-field rules.
- Precognition (`HandlePrecognitiveRequests`) gives live validation to
  Inertia and Livewire forms without duplicating rules.

## Responses and resources

- Return resources from APIs, never models or arrays built by hand.
- `InvoiceResource::make($invoice)` returns 200, or 201 automatically when
  the model was just created (`wasRecentlyCreated`).
- Paginate collections: `cursorPaginate(25)` for APIs.
- Use `whenLoaded('lines')` and `whenCounted('lines')` so resources never
  trigger lazy loads.
- Stream big exports with `response()->streamDownload()` or a queued job
  plus a signed download URL, never by building the whole file in memory.

## JSON:API resources

For public or partner APIs, use Laravel 13's `JsonApiResource`
(`php artisan make:resource InvoiceResource --json-api`). It handles
resource objects, `include`, sparse fieldsets, links, and the
`application/vnd.api+json` content type. Declare `$attributes` and
`$relationships`, or override `toAttributes()`. Pair it with
spatie/laravel-query-builder to parse `filter` and `sort` safely against an
allow-list. For internal APIs (your own frontend or mobile app), plain
`JsonResource` is simpler.

## Authentication: web, SPA, mobile, third parties

| Client | Use |
|---|---|
| Server-rendered web (Blade, Livewire, Inertia) | Session auth from the starter kit (Fortify under the hood) |
| First-party SPA on the same top-level domain | Sanctum SPA (cookie) auth, `statefulApi()` |
| Mobile (NativePHP or native) and CLI clients | **Sanctum tokens** with `expiration` set, abilities, and a refresh flow |
| Third parties acting for your users | Passport (OAuth2 server) |
| Sign in with Google, GitHub, and so on | Socialite |
| Enterprise SSO | WorkOS starter kit, or a SAML package |

- **Sanctum tokens never expire by default.** Set `'expiration'` in
  `config/sanctum.php` (for example, 60 × 24 × 7 minutes for mobile), and
  schedule `sanctum:prune-expired`.
- Issue tokens with abilities (`createToken('ios', ['invoices:read'])`) and
  check them with `tokenCan()` or the `abilities` middleware.
- Name the token after the device and let users revoke tokens.
- Enable 2FA through the starter kit (Fortify). Rate-limit login
  (`throttle:login`, already in the kits).

## Rate limiting

Define named limiters in `AppServiceProvider::boot()`:

```php
RateLimiter::for('api', fn (Request $request) => Limit::perMinute(120)
    ->by((string) ($request->user()->id ?? $request->ip())));
```

Key by user when authenticated and by IP otherwise. Behind Cloudflare,
the IP must come from trusted proxy headers (see `deploy-and-operate.md`),
or every visitor shares Cloudflare's IP. Use stricter limiters for login,
password reset, and anything that sends email or SMS.

## Errors

- `bootstrap/app.php` → `withExceptions()` is the single place for
  reporting and rendering. `shouldRenderJsonWhen(fn ($r) => $r->is('api/*') || $r->expectsJson())`
  is in the skeleton.
- Domain exceptions render themselves (`render()` returning a 422 JSON
  response for JSON clients).
- Validation gives 422 with `errors`, authorization gives 403, and a
  missing model gives 404. Don't reinvent the envelope.
- Never leak exception messages from unexpected errors. `APP_DEBUG=false`
  does that for you.

## Versioning and evolution

- Evolve additively: add fields, never rename or remove them. Deprecate with
  a date and a `Sunset` header.
- When a breaking change is unavoidable, version the route prefix
  (`/api/v2`), with separate controllers and resources that call the same
  actions.
- For type-safe frontends, Inertia apps use Wayfinder (generated TypeScript
  for routes and controller actions). For external clients, publish an
  OpenAPI document (for example, with dedoc/scramble, which reads Form
  Requests and resources).

## Webhooks in and out

- **Inbound:** a dedicated route outside the CSRF-protected web group (or
  excluded by URI only), a signature check first (Stripe's with Cashier,
  HMAC for others), then store the payload and queue a job. Respond 200
  fast, and make the handler idempotent on the provider's event id.
- **Outbound:** queued jobs with `#[Tries]` and `#[Backoff]`, a signed
  payload, and a timeout on the HTTP client:
  `Http::timeout(10)->retry(3, 200)->post(...)`. Use
  spatie/laravel-webhook-server if you send many.
