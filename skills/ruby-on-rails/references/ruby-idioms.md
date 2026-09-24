# Modern Ruby for Rails code

Target Ruby 3.4 or 4.0. Optimize for the reader: one obvious way, and short
methods named after the domain.

## Use

- **Keyword arguments** for anything beyond one or two obvious positional
  arguments: `pay(amount:, paid_at: Time.current)`. Shorthand hash syntax
  (`create!(name:, email_address:)`) is fine when the local variable and key
  match.
- **Endless methods** for true one-liners: `def total = line_items.sum(:amount)`.
  Never use them for multi-step logic.
- **`Data.define`** for immutable value objects:
  `Money = Data.define(:cents, :currency) do def to_s = format("%.2f %s", cents / 100.0, currency) end`.
- **Pattern matching**, for parsing structured input (webhooks, API responses):
  ```ruby
  case payload
  in { type: "invoice.paid", data: { id: String => id } } then Invoice.find_by!(external_id: id).mark_paid
  in { type: String => type } then Rails.logger.info("ignored webhook #{type}")
  end
  ```
- **`it`** (Ruby 3.4+) for a trivial single-argument block:
  `names.map { it.strip }`. Use a named argument when the block is more than
  a few tokens.
- **Guard clauses** instead of nested conditionals:
  `return if invoice.paid?`.
- **Safe navigation (`&.`)** only where `nil` is a legitimate state. Don't use
  it to paper over bugs.
- **Frozen, meaningful constants:** `STATUSES = %w[ draft sent paid ].freeze`.
- **Enumerable fluency:** `sum`, `index_by`, `group_by`, `partition`,
  `each_with_object`, `filter_map`, `tally`, `each_slice`.
- **Composition via small objects** (operations, forms, queries, value
  objects) rather than deep inheritance. Beyond the framework's own base
  classes, `ApplicationResult` is the only shared abstraction.

## Avoid in application code

- `method_missing` and `define_method` loops, `send` with user input, and
  `instance_variable_get`. Metaprogramming belongs in frameworks and gems, not
  in your domain.
- Monkey-patching core classes. If you truly need it, use refinements, or a
  clearly named initializer that's tested.
- `rescue Exception`, or a bare `rescue => e` that swallows errors. Rescue
  specific errors, and let the rest reach the error reporter.
- `and`/`or` for control flow, nested ternaries, `unless ... else`, and
  multi-line blocks with `{}`.
- Mutating arguments. Return new values instead. Keep bang methods (`!`) only
  where there's a non-bang counterpart, or to signal raising or danger.
- Class variables (`@@`) and global state. Use `Current` or configuration
  objects.
- Experimental features in production: `Ruby::Box`, ZJIT, and multi-Ractor
  code in app servers.

## Style

The linters are `rubocop-rails`, `rubocop-rspec`, and `rubocop-factory_bot`,
with Sandi Metz's metrics enforced (`assets/.rubocop.yml`):
- classes of 100 lines or fewer;
- methods of 5 lines or fewer (arrays, hashes, and heredocs count as one
  line);
- 4 parameters or fewer.

CI runs with zero warnings allowed. Beyond the config, follow these
conventions:
- Use double-quoted strings.
- Indent private methods one level under `private`.
- Order a class as: constants, includes, associations, validations,
  callbacks, scopes, then public methods, then private methods.
- Name operations VerbNoun (`Billing::RecordPayment`), components
  NounComponent, and policies ModelPolicy.
- Don't bikeshed beyond the config. Add a cop only after repeated review
  comments.

## Gem hygiene

- Every new gem needs an answer to "what would it take to write this
  ourselves in 50 lines?" If the answer is 50 lines, write the 50 lines.
- Prefer gems maintained by the Rails core team or with long track records.
  Check release activity and open issues.
- Pin major versions in the Gemfile only when necessary (`"~> 8.1"`). Let
  `Gemfile.lock` do the pinning.
