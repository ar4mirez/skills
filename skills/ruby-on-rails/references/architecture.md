# Architecture: the modular majestic monolith

One Rails app and one deploy, with **hard internal boundaries**. Business
capabilities live in **bounded contexts** under `app/domains/<domain>/`, and
Packwerk enforces the boundaries. HTTP (controllers, views, components) is a
thin **interface layer** on top of those domains. Every kind of object has
exactly one home and one shape, so the code is predictable without being
clever.

## Contents
- The layers
- Directory layout and Zeitwerk setup
- Domains and Packwerk (boundaries, public API)
- Models: data, associations, invariants
- Service objects (domain operations)
- Form objects
- Query objects
- Controllers: thin and REST-only
- Views: ViewComponent + partials
- Jobs, mailers, and side effects
- Authorization (Pundit)
- Current attributes and the shared kernel
- Sandi Metz rules (enforced)
- Growing the architecture (keep it simple first)
- Existing codebases

## The layers

```
Interface layer   app/controllers, app/views, app/components, app/javascript
                  (web + Hotwire Native share it), app/mailers (templates)
Domain layer      app/domains/<domain>/: models, operations, forms, queries, jobs, public API
Shared kernel     app/models: ApplicationRecord, Current, and the few core entities
                  every domain needs (Account, User)
Infrastructure    config/, db/, Solid Queue/Cache/Cable, OpenSearch, PgBouncer, Kamal
```

Dependencies flow **downward only**. Interface code calls a domain's
**public** API. Domains call other domains only through those domains'
public APIs. The kernel depends on nothing.

## Directory layout and Zeitwerk setup

```
app/
  models/                         # shared kernel only
    application_record.rb
    current.rb
    account.rb
    user.rb
  domains/
    identity/                     # sign-in, sessions, MFA, invitations
      package.yml
      public/…
    billing/
      package.yml
      public/                     # the ONLY constants other packages may reference
        checkout.rb               # Billing::Checkout (facade)
      models/
        invoice.rb                # Billing::Invoice  (table: billing_invoices)
        subscription.rb
      operations/
        create_checkout.rb        # Billing::CreateCheckout.call(...)
        record_payment.rb
      forms/
        checkout_form.rb          # Billing::CheckoutForm
      queries/
        overdue_invoices.rb       # Billing::OverdueInvoices
      jobs/
        charge_subscription_job.rb
    communications/
      package.yml
      public/notify.rb            # Communications::Notify
      operations/…
  controllers/
    billing/checkouts_controller.rb     # Billing::CheckoutsController
  components/                           # ViewComponent
    billing/invoice_row_component.rb
  views/
  policies/                             # Pundit (interface-layer authorization)
packwerk.yml
package.yml                             # root package (everything not in a domain)
```

Make the layer folders (`models/`, `operations/`, and so on) organizational
only, so constants stay `Billing::Invoice`, not `Billing::Models::Invoice`:

```ruby
# config/initializers/domains.rb (collapse layer folders inside each domain)
Rails.autoloaders.main.collapse(
  Rails.root.join("app/domains/*/{public,models,operations,forms,queries,jobs}")
)
```

```ruby
# app/domains/billing.rb (namespace, with a table prefix so tables are billing_*)
module Billing
  def self.table_name_prefix = "billing_"
end
```

`app/domains` is autoloaded automatically, because every subdirectory of
`app/` is an autoload root. Generators don't know this layout, so move the
generated files, or write them by hand.

## Domains and Packwerk (boundaries, public API)

- **One domain per business capability,** named with a noun that the business
  uses: `billing`, `identity`, `communications`, `catalog`, `scheduling`. Don't
  name domains after technical layers (`api`, `utils`).
- `bundle add packwerk packwerk-extensions --group=development,test`, then
  `bin/packwerk init`. Packwerk core enforces **dependencies**.
  `packwerk-extensions` adds the **privacy** checker, which is what makes
  "only through the public API" real.

```yaml
# packwerk.yml
include:
  - "{app,lib}/**/*.{rb,rake,erb}"
exclude:
  - "{bin,node_modules,script,tmp,vendor}/**/*"
require:
  - packwerk-extensions
```

```yaml
# app/domains/billing/package.yml
enforce_dependencies: true
enforce_privacy: true
public_path: app/domains/billing/public/
dependencies:
  - "."                         # shared kernel (root package)
  - app/domains/communications  # billing may call Communications' public API
```

- **The public API is small:** a facade (`Billing::Checkout`) or a few
  operations re-exposed in `public/`, taking and returning kernel models,
  ids, or `Data` values. Never expose another domain's internal Active Record
  models across the boundary.
- **Cross-domain side effects** go through the other domain's public
  operation, preferably from a job (`Communications::Notify.later(...)`), so
  domains stay decoupled at runtime too. Don't use a pub/sub event bus
  until there's a real need.
- **CI runs `bin/packwerk check`,** and `package_todo.yml` records existing
  violations. The rule: the todo list may only shrink. Run
  `bin/packwerk validate` after changing package.yml files.
- **No cycles.** If two domains need each other, one of them is wrong, or the
  shared piece belongs in the kernel.

## Models: data, associations, invariants

A model owns **persistence and invariants**: associations, validations,
normalization, enums, scopes, and small derived predicates. Multi-step
business mutations live in operations.

```ruby
module Billing
  class Invoice < ApplicationRecord
    belongs_to :account
    has_many :line_items, dependent: :destroy
    has_many :payments, dependent: :restrict_with_error

    enum :status, %w[ draft sent paid void ].index_by(&:itself), default: :draft, validate: true

    validates :number, presence: true, uniqueness: { scope: :account_id }
    normalizes :number, with: ->(number) { number.strip.upcase }

    scope :chronologically, -> { order(:issued_on, :id) }

    def balance_due = total - payments.sum(:amount_cents)
    def total = line_items.sum(:amount_cents)
    def payable? = sent? && balance_due.positive?
  end
end
```

Rules:
- Allowed in models: associations, validations, `normalizes`, enums (string
  backed), scopes, and short query-free or single-query predicates and
  calculations.
- Not allowed in models: orchestration across records or domains, external
  API calls, sending mail, or enqueueing cross-domain work. Those are
  operations.
- Keep models under 100 lines (Sandi Metz). A growing model is asking for an
  operation, a query object, or a value object.
- Mirror every validation that guards data integrity with a database
  constraint (NOT NULL, FK, unique index, check).

## Service objects (domain operations)

**One convention, everywhere.** Name them VerbNoun: `CreateCheckout`,
`RecordPayment`, `CancelSubscription`. Each has one public `call`, keyword
arguments, and returns a `Result`.

```ruby
# app/models/application_result.rb (kernel; the ONLY result type in the app)
ApplicationResult = Data.define(:value, :errors) do
  def self.success(value = nil) = new(value:, errors: [])
  def self.failure(*errors) = new(value: nil, errors: errors.flatten)
  def success? = errors.empty?
  def failure? = !success?
end
```

```ruby
# app/domains/billing/operations/record_payment.rb
module Billing
  class RecordPayment
    def self.call(...) = new(...).call

    def initialize(invoice:, amount_cents:, paid_at: Time.current)
      @invoice = invoice
      @amount_cents = amount_cents
      @paid_at = paid_at
    end

    def call
      return ApplicationResult.failure("Invoice isn't payable") unless @invoice.payable?

      payment = @invoice.transaction { create_payment.tap { settle_invoice } }
      ApplicationResult.success(payment)
    end

    private
      def create_payment = @invoice.payments.create!(amount_cents: @amount_cents, paid_at: @paid_at)

      def settle_invoice
        @invoice.update!(status: :paid) if @invoice.balance_due.zero?
      end
  end
end
```

Rules:
- Use `.call(...)` in and out. There's no base class and no service
  framework: no `dry-monads`, `interactor`, or `trailblazer`.
  `ApplicationResult` is the only shared abstraction.
- **Return a Result for expected failures** (business rules, validation).
  **Raise for the unexpected** (`ActiveRecord::RecordInvalid` inside
  `create!` means a bug or a race; let it surface).
- Wrap the operation's own writes in one transaction. Enqueue side effects
  (mail, other domains, webhooks) **after** commit. Rails 8 enqueues jobs
  after the transaction commits by default, so enqueue from inside the
  operation freely.
- Keep them small: under 5 lines per method and under 100 lines per class.
  If an operation needs more, it's two operations, or it needs a form or
  query object.
- Don't add `*Service` suffixes and don't create `app/services`. The folder is
  `operations/` inside a domain, and the name is the verb.

## Form objects

Use a form object when a form doesn't map one-to-one to a model: multi-model
signup, checkout, or wizard steps.

```ruby
module Billing
  class CheckoutForm
    include ActiveModel::Model
    include ActiveModel::Attributes

    attribute :plan_id, :integer
    attribute :seats, :integer, default: 1
    attribute :coupon_code, :string

    validates :plan_id, presence: true
    validates :seats, numericality: { greater_than: 0, only_integer: true }

    def to_operation_args = { plan_id:, seats:, coupon_code: coupon_code.presence }
  end
end
```

Form objects validate and shape input. They don't persist. The controller
passes `form.to_operation_args` to the operation. Use `form_with model:
@form, url: billing_checkout_path`.

## Query objects

Keep reusable one-liners as scopes. Use a query object for anything with
joins, grouping, or several parameters:

```ruby
module Billing
  class OverdueInvoices
    def self.call(account:, as_of: Date.current) = new(account:, as_of:).call

    def initialize(account:, as_of:)
      @account = account
      @as_of = as_of
    end

    def call
      Invoice.where(account: @account).sent.where(due_on: ...@as_of).includes(:customer).chronologically
    end
  end
end
```

Return relations (they stay composable and paginatable), and never arrays of
records. Never use `default_scope`.

## Controllers: thin and REST-only

```ruby
# config/routes.rb
namespace :billing do
  resource :checkout, only: %i[new create]
  resources :invoices, only: %i[index show] do
    resources :payments, only: %i[new create], module: :invoices
  end
end
```

```ruby
class Billing::CheckoutsController < ApplicationController
  def new
    @form = Billing::CheckoutForm.new
  end

  def create
    @form = Billing::CheckoutForm.new(checkout_params)
    return render(:new, status: :unprocessable_entity) if @form.invalid?

    result = Billing::Checkout.start(account: Current.account, **@form.to_operation_args)
    if result.success?
      redirect_to billing_invoice_path(result.value), status: :see_other
    else
      @form.errors.add(:base, result.errors.to_sentence)
      render :new, status: :unprocessable_entity
    end
  end

  private
    def checkout_params = params.expect(billing_checkout_form: [ :plan_id, :seats, :coupon_code ])
end
```

Rules:
- Use only the seven actions. Any other verb becomes a new resource with its
  own controller (`resource :publication`, not `post :publish`).
- A controller does four things: authorize, parse params (`params.expect`),
  call **one** domain entry point, and respond. Expose **one** instance
  variable to the view (Sandi Metz).
- **Scope every lookup through the tenant or user**
  (`Billing::Invoice.where(account: Current.account).find(params.expect(:id))`),
  and authorize with Pundit.
- Controllers call a domain's public API. `bin/packwerk check` catches reaches
  into its internals.

## Views: ViewComponent + partials

- Every reusable UI element is a **ViewComponent** in `app/components`, such
  as buttons, badges, cards, tables, empty states, and form fields. A
  component has a Ruby class plus a template, and it's unit-tested in
  isolation, with previews in Lookbook (optional).
- Plain partials are for page-specific chunks that aren't reused. Don't put
  logic in partials. If it needs logic, it's a component.
- Components receive plain values or models through `initialize` keyword
  arguments. They never query the database or read `Current`.
- Tailwind classes live in components, so the design system is the component
  library.

See `hotwire.md` for Turbo and Stimulus inside components.

## Jobs, mailers, and side effects

- **Jobs live in their domain** (`app/domains/billing/jobs/`), are thin, pass
  ids or GlobalID, are idempotent, and call one operation.
- Use `ActiveJob::Continuable` for long multi-step work (imports, exports).
- **Mailers** and their templates stay in the interface layer
  (`app/mailers/billing/invoice_mailer.rb`), and are triggered by operations
  via `deliver_later`, never from model callbacks.
- **Callbacks** are only for the model's own consistency (normalizing,
  touching). Never re-save the record from its own callbacks, and never use a
  callback for cross-record or cross-domain work.
- **Cross-domain notification:** the billing operation calls
  `Communications::Notify.later(user:, template: :invoice_paid, invoice_id:)`,
  which is Communications' public API. It decides email, push
  (`action_push_native`), or SMS.

## Authorization (Pundit)

- `app/policies/<domain>/<model>_policy.rb`, one policy per resource, plus
  explicit role policies (`WorkspacePolicy`, `AdminPolicy`).
- Call `authorize @invoice` in every action that touches a record, and
  `policy_scope(Billing::Invoice)` for index queries. Add `after_action
  :verify_authorized` (and `verify_policy_scoped` for index) in
  `ApplicationController`, so a forgotten check fails in tests.
- Policies answer "may this user do this?". Tenant scoping (`Current.account`)
  still happens first, as defense in depth.

## Current attributes and the shared kernel

- `Current` (from the Rails 8 authentication generator) holds `session`,
  `user`, and `account`. The interface layer reads it. **Operations take what
  they need as keyword arguments** (`account:`, `user:`), so they stay
  testable and usable from jobs.
- The kernel (`app/models`) holds `ApplicationRecord`, `ApplicationResult`,
  `Current`, `Account`, `User`, and `Session`. Keep it tiny.
- **The kernel never references domain constants.** Don't write
  `has_many :billing_invoices` on `Account`. Domains point *to* the kernel
  (`belongs_to :account`) and scope with `where(account:)`, so dependencies
  keep flowing one way. If something
  there grows domain behavior, move that behavior into a domain.

## Sandi Metz rules (enforced)

1. Classes: 100 lines or fewer.
2. Methods: 5 lines or fewer.
3. Methods: 4 parameters or fewer (keyword arguments count; use an object or a
   hash when the list grows).
4. Controllers: expose one instance variable to the view.

Rules 1–3 are enforced by RuboCop (`assets/.rubocop.yml`), and rule 4 by
review. You may break a rule only with a comment explaining why, which is how
Sandi frames it: break it only if you can convince your pair.

## Growing the architecture (keep it simple first)

Simplicity still wins. Adopt structure as it earns its keep:
1. **Day one:** a kernel (`app/models`), one or two domains under
   `app/domains`, Packwerk with dependency *and* privacy checks, `bin/packwerk
   check` in CI, and the operation/form/query conventions above.
2. **A new capability:** a new domain, but only when it has its own models and
   language. Otherwise it belongs in an existing domain.
3. **A domain gets big:** split it along business language (`billing` →
   `billing` + `metering`), never along technical layers.
4. **Extracting a service:** only when a domain has a genuinely different
   scaling, compliance, or team or release profile, justified in writing.
   The Packwerk public API makes that extraction straightforward.

Don't add these early: event buses, CQRS, repositories wrapping Active Record,
dependency-injection containers, or an interface/port layer. Active Record
*is* the repository.

## Existing codebases

- **Follow the conventions already present** (a flat `app/models`, services
  in `app/services`, Minitest). Consistency beats this guide.
- **Migrate incrementally:**
  1. Add Packwerk with a `package_todo.yml`.
  2. Carve out one domain.
  3. Move its services into `operations/` with VerbNoun names.
  4. Shrink the todo list over time.

  Never do a big-bang restructure.
