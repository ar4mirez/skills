# Testing

Default to **Minitest + fixtures**, the Rails default: fast, zero-config, and
readable. If the app already uses RSpec + FactoryBot, write RSpec in the same
style. The principles below apply either way.

## What to test, at which level

| Level | Tests | Share of suite |
|---|---|---|
| **Model** (`test/models`) | Domain behavior: methods, scopes, validations that encode rules, POROs | Most |
| **Controller/request** (`test/controllers`, `ActionDispatch::IntegrationTest`) | The HTTP contract: status, redirects, auth and tenant scoping, params, turbo-stream responses | Some |
| **System** (`test/system`, Capybara + Selenium/Cuprite) | Critical user journeys end to end: signup, checkout, the core workflow | Few (roughly 5–20) |
| **Job/Mailer** | That the job calls the model method; mailer content and recipients | Few |

Don't write tests that restate framework behavior (`validates presence`
without a rule behind it, `belongs_to` existence), or view tests for markup
details.

## Fixtures: a small, named world

```yaml
# test/fixtures/accounts.yml
acme:
  name: Acme Inc.

# test/fixtures/users.yml
david:
  account: acme
  email_address: david@acme.test
  password_digest: <%= BCrypt::Password.create("secret", cost: 4) %>
  role: owner

# test/fixtures/invoices.yml
acme_draft:
  account: acme
  customer: globex
  number: INV-001
  status: draft
```

- Name fixtures like characters in a story (`acme_draft`, `overdue_sent`), so
  tests read as scenarios.
- Keep them minimal. Add a fixture when a test needs a new situation, not "just
  in case."
- Build rare variations inline with `invoices(:acme_draft).dup.tap { ... }`,
  or with `update!` in the test.
- Fixtures load once per run inside transactions, which is why they're much
  faster than factories.

## Examples

```ruby
class InvoiceTest < ActiveSupport::TestCase
  test "paying the full balance marks the invoice paid" do
    invoice = invoices(:acme_sent)

    invoice.pay(amount: invoice.total)

    assert invoice.reload.paid?
  end

  test "overdue includes only sent invoices past due" do
    travel_to Date.new(2026, 10, 1) do
      assert_includes Invoice.overdue, invoices(:acme_sent_due_september)
      assert_not_includes Invoice.overdue, invoices(:acme_draft)
    end
  end
end
```

```ruby
class InvoicesControllerTest < ActionDispatch::IntegrationTest
  setup { sign_in_as users(:david) }

  test "cannot see another account's invoice" do
    get invoice_url(invoices(:globex_sent))
    assert_response :not_found
  end

  test "invalid invoice re-renders with 422" do
    post invoices_url, params: { invoice: { number: "" } }
    assert_response :unprocessable_entity
  end
end
```

```ruby
class SendInvoiceTest < ApplicationSystemTestCase
  test "owner sends a draft invoice" do
    sign_in_as users(:david)
    visit invoice_url(invoices(:acme_draft))
    click_on "Send invoice"
    assert_text "Invoice sent."
  end
end
```

- Structure each test as arrange / act / assert, separated by blank lines,
  with one behavior per test. The test name states the rule.
- Use `travel_to` for time, and `assert_enqueued_with(job: ...)` or
  `perform_enqueued_jobs` for jobs.
- Use `assert_emails 1 { ... }` and `ActionMailer::Base.deliveries` for mail.
- For external HTTP, use WebMock with explicit stubs. Put a thin client object
  behind the model so tests stub at one seam. Use VCR only for complex
  third-party APIs.
- The authentication generator gives you `sign_in_as`, via a
  `SessionTestHelper`, in modern Rails. If it's missing, add a helper that
  posts to `session_url`.

## Keeping the suite fast

- Run tests in parallel (`parallelize(workers: :number_of_processors)`, which
  is the default).
- Use fixtures, not factories. If using factories, prefer `build_stubbed` or
  `build`.
- Don't hit the network, and don't `sleep`.
- Keep system tests few, and on headless Chrome.
- Aim to keep the full model and controller suite under about a minute on a
  laptop.

## CI

Rails 8.1 local CI lives in `config/ci.rb` (see `assets/ci.rb`) and runs with
`bin/ci`. It covers setup, RuboCop, bundler-audit, importmap audit, Brakeman,
tests, system tests, and seeds. Keep the generated GitHub Actions workflow as
well, or use `gh signoff` so passing local CI gates merges.

Test Hotwire Native apps on the Rails side. Request tests with a native user
agent assert native-specific behavior:

```ruby
get invoice_url(invoice), headers: { "User-Agent" => "Hotwire Native iOS" }
assert_select "nav.web-only", count: 0
```
