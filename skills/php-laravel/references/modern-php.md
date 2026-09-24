# Modern PHP (8.4 / 8.5)

Every feature below was run on PHP 8.5.11. Use them where they make code
clearer, not to show them off.

## Contents
- Baseline rules
- Types and classes
- PHP 8.4 features
- PHP 8.5 features
- Enums
- Errors
- Idioms to prefer
- Avoid in application code
- Style (Pint)

## Baseline rules

- `declare(strict_types=1);` at the top of every PHP file (Pint rule
  `declare_strict_types`, arch rule `toUseStrictTypes()`). Without it,
  `"5 apples"` silently becomes `5`.
- Every parameter, property, and return is typed (Pest `--type-coverage
  --min=100`). Use docblock generics (`list<string>`, `array<string, int>`,
  `Collection<int, Invoice>`) where PHP's types stop.
- Classes are `final` by default (Pint `final_class`). Open one only for a
  reason.
- Value objects and DTOs are `final readonly class` with constructor
  promotion.
- `===` only (Pint `strict_comparison`).

## Types and classes

```php
final readonly class InvoiceData
{
    public function __construct(
        public string $customerEmail,
        public int $amountCents,
        public string $currency,
        public CarbonImmutable $dueOn,
    ) {}
}
```

- Named arguments at call sites with several same-typed parameters:
  `new InvoiceData(customerEmail: ..., amountCents: ...)`. (Laravel
  excludes named arguments from its backward-compatibility promise, so
  avoid them for *framework* methods whose parameter names may change.)
- Union and nullable types are fine, but `mixed` is a smell outside
  framework boundaries.
- `never` for functions that always throw or exit.
- First-class callables: `array_map(strtoupper(...), $names)`.

## PHP 8.4 features

- **Property hooks** for derived or validated properties:
  `public string $formatted { get => number_format($this->cents / 100, 2); }`.
  Keep hooks trivial. Anything with I/O is a method.
- **Asymmetric visibility**: `public private(set) int $cents;`, readable
  everywhere and writable only inside the class. It's a lighter
  alternative to readonly when the class itself mutates the value.
- **`new` without parentheses in chains**: `new Point(1, 2)->withY(9)`.
- **`array_find()`, `array_find_key()`, `array_any()`, `array_all()`.**
- `#[\Deprecated]` on your own functions and methods.
- Lazy objects (`ReflectionClass::newLazyGhost()`) are for frameworks and
  containers, not app code.

## PHP 8.5 features

- **Pipe operator** for left-to-right transforms:
  `$slug = $title |> trim(...) |> strtolower(...) |> (fn ($s) => preg_replace('/\W+/', '-', $s));`
  Use it for short pure pipelines; a named method reads better past three
  steps.
- **`clone` with properties**, for withers on readonly classes:
  ```php
  public function withY(int $y): self { return clone($this, ['y' => $y]); }
  ```
  It only works **inside the class** for readonly properties, because
  readonly implies `protected(set)`. `clone($point, ['y' => 9])` from
  outside throws "Cannot modify protected(set) readonly property".
- **`array_first()` / `array_last()`.**
- **`#[\NoDiscard]`** on functions whose return value must be used (an
  immutable wither, a `Result`). Ignoring it raises a warning; use
  `(void) f()` to discard on purpose.
- **URI extension**: `Uri\Rfc3986\Uri::parse($url)` (and `Uri\WhatWg\Url`)
  for standards-compliant URL parsing, instead of `parse_url()`, which has
  well-known edge cases.
- **`#[\Override]` on properties** too (Rector's PHP 8.5 set adds it to
  overridden model properties such as `$attributes`).
- Closures and first-class callables are allowed in constant expressions
  (attribute arguments, constants).

Remember: NativePHP Mobile embeds PHP 8.4, and libraries you publish
should support 8.4. Keep 8.5-only syntax to app code.

## Enums

```php
enum InvoiceStatus: string
{
    case Draft = 'draft';
    case Sent = 'sent';
    case Paid = 'paid';
    case Void = 'void';

    public function isPayable(): bool { return $this === self::Sent; }
    public function label(): string { return ucfirst($this->value); }
}
```

- Backed string enums for anything stored. Cast them on models and
  validate them with `Rule::enum()`.
- Put behavior on the enum (`isPayable()`) instead of `match` statements
  scattered around the codebase.
- `tryFrom()` for untrusted input (it returns null), `from()` when an invalid
  value is a bug.
- `match` must be exhaustive. Let it throw `UnhandledMatchError` on a new
  case rather than adding a silent `default`.

## Errors

- Throw specific exceptions with named constructors
  (`InvoiceNotPayable::because(...)`). Catch only what you can handle.
- Never catch `\Throwable` or `\Exception` to hide failures. Let the
  handler report them.
- Don't return `false` or `null` for errors in new code. Throw, or return a
  typed result object when failure is a normal outcome.

## Idioms to prefer

- Guard clauses and early returns (Rector's `earlyReturn` set).
- Collections (`collect()`, `->map()`, `->filter()`, `->groupBy()`,
  `->sum()`) for in-memory data; SQL for database data.
- `Str::of($x)->...` and `Number::` helpers over hand-rolled formatting.
- `match` over `switch`.
- `?->` only where null is a legitimate state, not to paper over bugs.
- `sprintf` or interpolation, and `Str::` helpers. No `.` chains across
  five lines.

## Avoid in application code

- `extract()`, `compact()` with long lists (fine for small view data),
  variable variables, `global`, `eval`, `@` error suppression, and
  `goto`.
- Static state (`static $cache`) in services. It breaks under Octane and in
  tests.
- Magic `__get` / `__call` in your own classes (it's fine in the framework).
- Traits as a code-sharing dumping ground. Use them for real cross-cutting
  behavior only (like `HasFactory`).
- Facades inside domain code you want to unit-test without the app; inject
  the contract. Facades in controllers, jobs, and providers are fine.
- Helper-function files (`app/helpers.php`) for business logic.

## Style (Pint)

`assets/pint.json`: the `laravel` preset plus `declare_strict_types`,
`final_class`, `strict_comparison`, `void_return`,
`fully_qualified_strict_types`, and global namespace imports. Run
`pint --parallel` via `composer fix`, and `pint --test` in CI. Don't
bikeshed beyond the config; add a rule only after repeated review
comments. Rector (`assets/rector.php`) handles upgrades and dead code:
`withPhpSets()`, `withComposerBased(laravel: true)`, the Laravel
code-quality and collection sets, and the prepared sets (dead code, code
quality, type declarations, early return).
