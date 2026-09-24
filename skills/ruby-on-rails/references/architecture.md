# Architecture: the opinionated Rails way

The goal: code that anyone fluent in Rails can navigate blind. Every rule here
trades a little flexibility for a lot of predictability.

## Contents
- Directory layout
- Models: rich, cohesive, constrained
- Plain Ruby objects (POROs) in app/models
- Concerns
- Callbacks: what's allowed
- Controllers: REST only
- Forms spanning models
- Queries and scopes
- Jobs, mailers, and side effects
- Current attributes
- Authorization
- Modularity at scale: namespaces → engines
- Naming
- When the codebase already differs

## Directory layout

```
app/
  models/
    account.rb
    account/
      billing.rb            # concern scoped to Account (module Account::Billing)
      closure.rb            # PORO: Account::Closure.new(account).close
    concerns/
      trashable.rb          # cross-model trait
    signup.rb               # PORO: domain operation, not "SignupService"
    current.rb              # ActiveSupport::CurrentAttributes
  controllers/
    concerns/authentication.rb
    accounts/closures_controller.rb   # nested resource instead of a custom action
  views/                    # ERB + partials; components/ only if ViewComponent is adopted
  jobs/                     # thin: find record, call one method
  mailers/
  javascript/controllers/   # Stimulus
lib/                        # code that isn't app-specific (could become a gem)
```

Things this layout deliberately doesn't have:
- **`app/services`**, **`app/interactors`**, and **`app/operations`**, as
  junk-drawer layers.
- A `dry-rb` or `trailblazer` stack. Those tools are fine elsewhere, but
  they're an alien dialect inside a Rails app.
- **`app/decorators`** by default. Use helpers or model presentation methods,
  and ViewComponent once there's a design system.

## Models: rich, cohesive, constrained

A model is the domain concept: its data, rules, and behavior. Write
intention-revealing methods rather than making callers manipulate attributes.

```ruby
class Invoice < ApplicationRecord
  include Trashable

  belongs_to :account
  belongs_to :customer
  has_many :line_items, dependent: :destroy

  enum :status, %w[ draft sent paid void ].index_by(&:itself), default: :draft

  validates :number, presence: true, uniqueness: { scope: :account_id }

  normalizes :number, with: -> { it.strip.upcase }

  scope :overdue, -> { sent.where(due_on: ...Date.current) }
  scope :chronologically, -> { order(:issued_on, :id) }

  def send_to_customer
    transaction do
      update!(status: :sent, sent_at: Time.current)
      InvoiceMailer.with(invoice: self).issued.deliver_later
    end
  end

  def pay(amount:, paid_at: Time.current)
    Invoice::Payment.new(self, amount:, paid_at:).record
  end

  def total = line_items.sum(:amount)
end
```

Rules:
- Put the API that callers use (`send_to_customer`, `pay`) on the model. Don't
  make callers do `invoice.update(status: "sent")` plus their own mailing.
- Use string-backed enums (`index_by(&:itself)`) so the database stays
  readable and reordering can't corrupt data.
- Use `normalizes` for canonical forms, not `before_validation` callbacks.
- Keep a model file readable in one sitting, around 200 lines. When it grows,
  extract **concerns for capabilities** and **POROs for processes**, not
  "helpers."

## Plain Ruby objects (POROs) in app/models

Use a PORO when an operation spans several records, has its own steps and
state, or deserves a name in the domain language.

```ruby
# app/models/invoice/payment.rb
class Invoice::Payment
  attr_reader :invoice, :amount, :paid_at

  def initialize(invoice, amount:, paid_at:)
    @invoice, @amount, @paid_at = invoice, amount, paid_at
  end

  def record
    invoice.transaction do
      invoice.payments.create!(amount:, paid_at:)
      invoice.update!(status: :paid) if invoice.balance_due.zero?
    end
  end
end
```

```ruby
# app/models/signup.rb (form + operation for a flow that creates several records)
class Signup
  include ActiveModel::Model
  include ActiveModel::Attributes

  attribute :name, :string
  attribute :email_address, :string
  attribute :password, :string

  validates :name, :email_address, :password, presence: true

  def save
    return false unless valid?

    ActiveRecord::Base.transaction do
      @account = Account.create!(name:)
      @user = @account.users.create!(email_address:, password:, role: :owner)
    end
    true
  rescue ActiveRecord::RecordInvalid => error
    errors.merge!(error.record.errors)
    false
  end

  attr_reader :account, :user
end
```

Rules for POROs:
- Name them with a noun, or a noun phrase for a process (`Invoice::Payment`,
  `Account::Closure`, `Import::Parser`), never `XService`.
- Give them one obvious public entry point with a domain verb (`record`,
  `close`, `parse`). `call` is acceptable only when the object *is* a
  function-like step in a pipeline.
- Return domain values or `true`/`false` plus `errors` (ActiveModel style).
  Raise for truly exceptional failures. Don't introduce `Result` monads in
  Rails apps.
- For value objects, use `Data.define(:amount, :currency)`: immutable, with
  value equality.

## Concerns

A concern captures **one capability** shared by several models, or it groups
one facet of a big model.

```ruby
# app/models/concerns/trashable.rb
module Trashable
  extend ActiveSupport::Concern

  included do
    scope :kept, -> { where(trashed_at: nil) }
    scope :trashed, -> { where.not(trashed_at: nil) }
  end

  def trash    = update!(trashed_at: Time.current)
  def restore  = update!(trashed_at: nil)
  def trashed? = trashed_at.present?
end
```

- Name concerns after the capability, as an adjective or role: `Trashable`,
  `Subscribable`, `Account::Billing`.
- A concern must make sense read on its own. If it only works with one host's
  private internals, it belongs inside that model file instead.
- Don't nest concerns inside concerns more than one level.

## Callbacks: what's allowed

Callbacks are allowed for:
- `normalizes`, derived attributes, and defaults (`before_validation` as a last
  resort);
- `touch: true` for cache invalidation;
- `after_create_commit`/`after_update_commit` to *enqueue* follow-up work, and
  `broadcasts_refreshes`.

Callbacks are not allowed for:
- sending email, calling external APIs, or charging cards from `after_save`
  (it runs inside the transaction, and a rollback leaves the side effect
  behind);
- creating or modifying *other* aggregates in ways a reader wouldn't expect.
  Make it an explicit method (`invoice.send_to_customer`).

Rule of thumb: if a test has to know about a callback to set up unrelated
data, the callback is doing too much.

## Controllers: REST only

```ruby
# config/routes.rb
resources :invoices do
  resource :delivery, only: :create, module: :invoices   # POST /invoices/:id/delivery
  resources :payments, only: %i[new create], module: :invoices
end
```

```ruby
# app/controllers/invoices/deliveries_controller.rb
class Invoices::DeliveriesController < ApplicationController
  include InvoiceScoped   # before_action :set_invoice, from Current.account.invoices

  def create
    @invoice.send_to_customer
    redirect_to @invoice, notice: "Invoice sent."
  end
end
```

```ruby
class InvoicesController < ApplicationController
  before_action :set_invoice, only: %i[show edit update destroy]

  def index
    @invoices = Current.account.invoices.kept.includes(:customer).chronologically
  end

  def create
    @invoice = Current.account.invoices.new(invoice_params)

    if @invoice.save
      redirect_to @invoice, notice: "Invoice created."
    else
      render :new, status: :unprocessable_entity
    end
  end

  private
    def set_invoice
      @invoice = Current.account.invoices.find(params.expect(:id))
    end

    def invoice_params
      params.expect(invoice: [ :customer_id, :number, :issued_on, :due_on ])
    end
end
```

Rules:
- Use the seven actions only (`index show new create edit update destroy`).
  Any other verb becomes a new singular or plural resource with its own
  controller. This keeps controllers tiny and routes self-documenting.
- **Scope every lookup through the tenant or user** (`Current.account.invoices.find`).
  That one habit prevents most authorization bugs.
- Use one or two instance variables per action, and don't put business logic
  in a controller. It orchestrates: find, call one model method, then
  respond.
- Shared `before_action` setup belongs in controller concerns
  (`InvoiceScoped`), not in inheritance chains.
- Use `render ..., status: :unprocessable_entity` for invalid forms, and
  `redirect_to ..., status: :see_other` after a non-GET request when Turbo
  needs it.

## Forms spanning models

- **One model:** use `form_with model: @invoice`, with
  `accepts_nested_attributes_for` only for true parent/child editing (line
  items).
- **Several models or a flow:** use an ActiveModel form object in
  `app/models` (see `Signup` above), with `form_with model: @signup, url:
  signup_path`.

## Queries and scopes

- **Named scopes** compose, so use them for reusable filters: `overdue`,
  `kept`, `chronologically`.
- **Class methods or a query PORO** handle complex reporting queries, for
  example `Invoice::AgingReport.new(account).rows`. Keep the SQL there, not in
  controllers.
- **Never use `default_scope`,** because it leaks into associations, joins,
  and `unscoped` bugs. Name the scope and call it.
- Prefer Active Record and Arel. Raw SQL is fine when it's clearer; use
  `sanitize_sql` and bind parameters.

## Jobs, mailers, and side effects

```ruby
class Invoice::ReminderJob < ApplicationJob
  queue_as :default
  retry_on Net::OpenTimeout, wait: :polynomially_longer, attempts: 5
  discard_on ActiveJob::DeserializationError

  def perform(invoice)
    invoice.remind_customer   # all logic lives on the model
  end
end
```

- Passing records works through GlobalID, which serializes the id. Make
  `perform` idempotent, because jobs can run twice.
- Use recurring work in `config/recurring.yml` (Solid Queue), not cron gems.
- For multi-step imports or exports, use `include ActiveJob::Continuable`
  with `step` and cursors, so deploys don't restart them from zero.
- Use `deliver_later` for mail. Mailers use `with(...)` params, and they're
  views, so keep logic in the model.

## Current attributes

`Current` (from the authentication generator) holds `session`, `user`, and
`account` for the request. Read it in controllers, models' defaults
(`belongs_to :creator, default: -> { Current.user }`), and jobs that set it
explicitly. Never use it as a global service locator in deep domain logic.
Pass arguments instead.

## Authorization

Start with predicates on the model and a guard in the controller:

```ruby
class Invoice
  def editable_by?(user) = draft? && user.can_administer?(account)
end

class InvoicesController
  before_action :ensure_editable, only: %i[edit update]

  private
    def ensure_editable
      head :forbidden unless @invoice.editable_by?(Current.user)
    end
end
```

Move to Pundit (one policy per model, plus `verify_authorized` in development
and test) when roles and rules outgrow a few predicates.

## Modularity at scale: namespaces → engines

Step through these stages in order, and stop at the first one that suffices:
1. **Namespaces**, such as `Billing::Invoice`, `app/models/billing/`, and
   `Billing::InvoicesController`, with routes under `namespace :billing`.
2. **Concerns and POROs** that keep each namespace's surface small.
3. **Engines in `engines/`** (or `packs/`), for a bounded context with its own
   models, routes, and tests, loaded as a path gem. They give you real
   boundaries while staying one deploy.
4. **Packwerk**, to *enforce* dependencies between packages once several teams
   collide.
5. **A separate service**, only for a genuinely different scaling or
   compliance profile, or an independent team and release cadence. It must be
   justified in writing.

## Naming

- **Models:** domain nouns (`Invoice`, `Recording`, `Membership`). Join models
  are named for the relationship, not `UserGroup`.
- **Methods:** use domain verbs (`publish`, `close`, `archive`). Predicates end
  in `?`, and dangerous or bang variants end in `!` (and raise).
- **Booleans in the database:** prefer timestamps (`archived_at`) over booleans
  (`archived`). You get the "when" for free.
- **Controllers:** plural resource names (`Invoices::PaymentsController`), or a
  singular resource for singletons (`resource :delivery`).

## When the codebase already differs

These opinions are defaults for new code. In an existing app:
- follow its established patterns for consistency, even ones you'd avoid, like
  services or RSpec;
- propose migrations toward these defaults as separate, incremental changes
  with reasons, never as a drive-by rewrite.
