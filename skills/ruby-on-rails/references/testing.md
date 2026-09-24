# Testing

Default to **RSpec + FactoryBot**, with Capybara system specs for Hotwire
flows, `rubocop-rspec` and `rubocop-factory_bot` for spec style, and
shoulda-matchers only for one-line association and validation specs. If an
existing app uses Minitest + fixtures, write Minitest in its style. Never mix
the two in one app.

Testing is part of design. If an operation is hard to test, its interface is
wrong: too many collaborators, hidden `Current` reads, or side effects that
aren't injected.

## Setup

```bash
rails new acme --database=postgresql --css=tailwind --skip-test   # no Minitest
bundle add rspec-rails factory_bot_rails shoulda-matchers --group=development,test
bundle add capybara selenium-webdriver webmock --group=test
bundle add rubocop-rspec rubocop-factory_bot --group=development --require=false
bin/rails generate rspec:install
```

```ruby
# spec/rails_helper.rb (additions)
require "webmock/rspec"
RSpec.configure do |config|
  config.include FactoryBot::Syntax::Methods
  config.include ActiveSupport::Testing::TimeHelpers
  config.include ActiveJob::TestHelper
  config.filter_rails_from_backtrace!
end
Shoulda::Matchers.configure { |c| c.integrate { |w| w.test_framework(:rspec); w.library(:rails) } }
WebMock.disable_net_connect!(allow_localhost: true)
```

Mirror the app's layout in `spec/`: `spec/domains/billing/operations/record_payment_spec.rb`,
`spec/requests/billing/checkouts_spec.rb`, `spec/components/...`,
`spec/system/...`, and `spec/policies/...`.

## What to test, at which level

| Level | Location | Tests | Share |
|---|---|---|---|
| **Operation** | `spec/domains/<d>/operations` | Every success and failure branch of a domain operation, its Result, and the side effects it enqueues | Most |
| **Model** | `spec/domains/<d>/models` | Invariants, scopes, predicates, and DB constraints (one-liners via shoulda) | Some |
| **Form/Query** | `spec/domains/<d>/{forms,queries}` | Validation rules, and the rows returned | Some |
| **Policy** | `spec/policies` | Each role allowed or denied, plus `Scope` | Some |
| **Request** | `spec/requests` | The HTTP contract: status, redirects, tenant isolation (404 for another account), `params.expect`, turbo-stream responses | Some |
| **Component** | `spec/components` | `render_inline(Component.new(...))` output for each variant | Some |
| **System** | `spec/system` | 5–20 critical journeys end to end (signup, checkout, the core workflow) | Few |

Don't write controller specs (use request specs), view specs, or specs that
restate the framework.

## Factories

```ruby
# spec/factories/billing/invoices.rb
FactoryBot.define do
  factory :billing_invoice, class: "Billing::Invoice" do
    account
    sequence(:number) { "INV-#{_1.to_s.rjust(4, '0')}" }
    status { :draft }

    trait :sent do
      status { :sent }
      issued_on { Date.current }
      due_on { 30.days.from_now.to_date }
    end

    trait :with_line_item do
      after(:create) { |invoice| create(:billing_line_item, invoice:, amount_cents: 10_000) }
    end
  end
end
```

- Keep factories minimal and valid: required attributes only. Build
  variations with **traits**.
- Prefer `build` or `build_stubbed` wherever persistence doesn't matter.
  `create` only for queries, constraints, and request or system specs.
- Keep associations explicit in the spec when they matter to the behavior
  (`create(:billing_invoice, account:)`).
- Don't nest `after(:create)` callbacks that build large graphs. Slow suites
  start there.

## Examples

```ruby
# spec/domains/billing/operations/record_payment_spec.rb
RSpec.describe Billing::RecordPayment do
  subject(:result) { described_class.call(invoice:, amount_cents:) }

  let(:invoice) { create(:billing_invoice, :sent, :with_line_item) }

  context "when the payment covers the balance" do
    let(:amount_cents) { 10_000 }

    it "records the payment and marks the invoice paid" do
      expect(result).to be_success
      expect(invoice.reload).to be_paid
    end
  end

  context "when the invoice isn't payable" do
    let(:invoice) { create(:billing_invoice) }   # draft
    let(:amount_cents) { 10_000 }

    it "fails without writing" do
      expect { result }.not_to change(Billing::Payment, :count)
      expect(result.errors).to include("Invoice isn't payable")
    end
  end
end
```

```ruby
# spec/requests/billing/invoices_spec.rb
RSpec.describe "Billing invoices" do
  let(:user) { create(:user) }

  before { sign_in_as(user) }

  it "hides other accounts' invoices" do
    other = create(:billing_invoice)
    get billing_invoice_path(other)
    expect(response).to have_http_status(:not_found)
  end

  it "re-renders an invalid checkout with 422" do
    post billing_checkout_path, params: { billing_checkout_form: { plan_id: "" } }
    expect(response).to have_http_status(:unprocessable_entity)
  end
end
```

```ruby
# spec/system/checkout_spec.rb
RSpec.describe "Checkout", type: :system do
  before { driven_by :selenium, using: :headless_chrome }

  it "subscribes to a plan" do
    sign_in_as create(:user)
    visit new_billing_checkout_path
    select "Pro", from: "Plan"
    click_on "Subscribe"
    expect(page).to have_text("You're subscribed")
  end
end
```

Conventions (enforced by rubocop-rspec):
- Use `describe` for the class or method, and `context` for the condition
  ("when...", "with...").
- Each example states one behavior. Use `subject` and `let` for setup, and
  avoid `let!` unless eager creation is the point.
- Use `travel_to` for time, `have_enqueued_job(Billing::ChargeSubscriptionJob)`
  and `have_enqueued_mail` for side effects, and `perform_enqueued_jobs` when
  the job's effect matters.
- For external HTTP, use WebMock stubs at one seam: the domain's client
  object. Keep VCR only for complex third-party APIs, and filter secrets.
- `sign_in_as` is a small request/system helper that posts to the session
  path (or sets the session cookie) for the Rails 8 authentication scaffold.
  Put it in `spec/support/authentication_helpers.rb`.

## Keeping the suite fast

- Run in parallel with the `parallel_tests` gem (`bin/parallel_rspec`),
  because Rails' built-in `parallelize` is Minitest-only. Allow no network
  and no `sleep`, and keep system specs few, on headless Chrome.
- `build_stubbed` over `create`, and use `let` lazily.
- Watch `rspec --profile 10`. Slow examples usually mean factory graphs.

## Quality gate (CI)

Zero warnings, with every step blocking merge:
1. `bin/rubocop` (`rubocop-rails`, `rubocop-rspec`, `rubocop-factory_bot`,
   and the Sandi Metz metrics, see `assets/.rubocop.yml`)
2. `bin/brakeman --no-pager --exit-on-warn --exit-on-error`
3. `bundle exec bundle-audit check --update` (and `bin/importmap audit`)
4. `bin/packwerk check` (boundaries, where `package_todo.yml` may only
   shrink)
5. `bundle exec rspec`, plus system specs

The GitHub Actions workflow is in `assets/github-ci.yml`. The same steps also
run locally through `config/ci.rb` / `bin/ci` (`assets/ci.rb`).

Hotwire Native: request specs with a native user agent assert native-specific
rendering:

```ruby
get project_path(project), headers: { "User-Agent" => "Hotwire Native iOS" }
expect(response.body).not_to include("web-navbar")
```
