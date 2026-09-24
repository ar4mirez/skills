# Frontend

**The rule: server-rendered first.** Livewire 4 plus Blade components is the
default, because one language, one repo, and one deploy keep a small team
fast. Choose Inertia 3 when the product is a rich client app or the team
already thinks in React or Vue. Never build a separate SPA repo against
your own API.

## Contents
- Choosing: Blade, Livewire, or Inertia
- Blade components
- Livewire 4
- Livewire security
- Inertia 3 + Wayfinder
- Filament 5 for admin
- Tailwind 4, Vite, and assets

## Choosing: Blade, Livewire, or Inertia

| Situation | Choose |
|---|---|
| Static or mostly-static pages | Blade + Blade components |
| CRUD, dashboards, forms, filters, live search | **Livewire 4** |
| Highly interactive client UI (editors, canvases, offline-ish SPA feel), or a React/Vue team | **Inertia 3** (React, Vue, or Svelte starter kit) |
| Internal admin or back office | **Filament 5** (built on Livewire) |
| Small sprinkles of client behavior | Alpine (ships with Livewire) |

Livewire's own guidance holds: extract a Blade component first, and make
it a Livewire component only when it needs server round-trips.

## Blade components

- Anonymous components in `resources/views/components/` for markup
  (`<x-button>`, `<x-card>`), with `@props([...])`. Class components only when
  they need logic.
- `{{ }}` escapes. `{!! !!}` doesn't: use it only for HTML you built and
  trust (for example, Markdown rendered through a sanitizer into an
  `HtmlString`).
- Pass models and data in; components don't query.
- Forms: `@csrf` (added automatically by the starter kits' form
  components), `@method('PATCH')`, and `@error('field')`.

## Livewire 4

Components are **single-file** by default (`php artisan make:livewire
invoices.index --sfc`), with the class and template in one
`⚡index.blade.php`. Pages live in `resources/views/pages` and route with
`Route::livewire()`. See `assets/livewire-invoices-index.blade.php`:

```php
<?php // resources/views/pages/invoices/⚡index.blade.php

new #[Title('Invoices')] class extends Component
{
    use WithPagination;

    #[Url]
    public string $status = '';

    #[Computed]
    public function invoices(): LengthAwarePaginator
    {
        $this->authorize('viewAny', Invoice::class);

        return Invoice::query()
            ->where('account_id', auth()->user()?->account_id)
            ->when(InvoiceStatus::tryFrom($this->status), fn ($q, InvoiceStatus $s) => $q->where('status', $s))
            ->latest('due_on')
            ->paginate(20);
    }

    public function markPaid(int $id, RecordPayment $recordPayment): void
    {
        $invoice = Invoice::query()->findOrFail($id);
        $this->authorize('pay', $invoice);
        $recordPayment->handle($invoice, $invoice->amount_cents);
        unset($this->invoices);   // bust the computed cache
    }
};
```

Conventions:
- Put view data in **`#[Computed]`** methods (cached per request, accessed
  as `$this->invoices`), not in public properties. Public properties are
  state that round-trips to the browser, so keep them to scalars and form
  fields.
- Actions call the same **Action classes** as controllers. Livewire
  methods can take injected dependencies after their parameters.
- Validate with `#[Validate]` on properties or a Form object
  (`extends Livewire\Form`) for bigger forms, then pass `$this->form->all()`
  or a DTO to the action.
- Use `wire:model.live.debounce.300ms` for search boxes, `wire:model`
  (deferred) for forms, and `wire:key` in every loop.
- Use `wire:navigate` for SPA-like page transitions, `@island` to re-render
  only part of a component, `lazy` for slow widgets, and `wire:poll`
  sparingly.
- Test with `Livewire::actingAs($user)->test('pages::invoices.index')->set(...)->call(...)`.
- Use Flux (the official component library) for polished UI; the free
  tier covers the basics.

## Livewire security

Every public property and every action argument can be set by the browser.
- **Re-query and authorize in every action** that takes an id.
  `scripts/laravel_audit.php` flags actions that call `find($id)` without
  `authorize`.
- Mark ids and other server-owned state with **`#[Locked]`**. Locked
  properties can't be changed from the client, but your own code can
  still set them from untrusted input, so authorize anyway.
- Prefer storing a model in a property over a raw id: Livewire locks a
  model property's id automatically, so it can't be swapped from the
  browser.
- Never `->get()` a whole table into a public property. It serializes into
  the page payload.

## Inertia 3 + Wayfinder

- Start from the React, Vue, or Svelte starter kit: Inertia 3, TypeScript,
  Tailwind 4, shadcn, Fortify auth, and **Wayfinder** for typed routes.
- Controllers stay the same shape: authorize, call an action, and
  `return Inertia::render('invoices/index', ['invoices' => InvoiceResource::collection(...)])`.
  Pass resources, never raw models: every prop is public in the page source.
- Use `Inertia::defer()` for slow props and partial reloads (`only: [...]`)
  instead of extra JSON endpoints.
- Share only what every page needs in `HandleInertiaRequests::share()`
  (the user's name, flashes, permissions), and do it lazily with closures.
- Wayfinder generates TypeScript functions for routes and controller
  actions. Import them instead of hard-coding URLs, and regenerate in the
  Vite build.
- SSR only for public, SEO-relevant pages. It adds a Node process to
  deploy.

## Filament 5 for admin

- Build internal tools and back office in Filament panels
  (`php artisan filament:install --panels`) at `/admin`, with its own guard
  or `canAccessPanel()` on the User model.
- Resources call the same actions for writes (in custom actions), and
  respect the same policies. Filament uses them automatically.
- Filament needs the `intl` extension. Add it to the Docker image (the
  asset Dockerfile does).
- Don't build customer-facing product UI in Filament. It's optimized for
  admin workflows, and customizing it past that fights the framework.

## Tailwind 4, Vite, and assets

- Tailwind 4 via `@tailwindcss/vite` (in the skeleton). Configure it in CSS
  (`@import "tailwindcss";` plus `@theme`), with no `tailwind.config.js`.
- `@vite(['resources/css/app.css', 'resources/js/app.js'])` in the layout.
  Build in CI and in the Docker image (`npm ci && npm run build`); never
  commit `public/build`.
- In tests, call `$this->withoutVite()` or views fail with "Vite manifest
  not found".
- Serve user uploads from S3 or R2 through a CDN, not from `public/`.
