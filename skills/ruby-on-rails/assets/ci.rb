# config/ci.rb (Rails 8.1 local CI, mirrors the GitHub Actions gate). Run with: bin/ci
CI.run do
  step "Setup", "bin/setup --skip-server"

  step "Style: RuboCop (rails, rspec, factory_bot, Metz metrics)", "bin/rubocop"
  step "Boundaries: Packwerk", "bin/packwerk check"

  step "Security: Gem audit", "bundle exec bundle-audit check --update"
  step "Security: Importmap vulnerability audit", "bin/importmap audit"
  step "Security: Brakeman", "bin/brakeman --quiet --no-pager --exit-on-warn --exit-on-error"

  step "Tests: RSpec", "bundle exec rspec --exclude-pattern 'spec/system/**/*_spec.rb'"
  step "Tests: System", "bundle exec rspec spec/system"
  step "Tests: Seeds", "env RAILS_ENV=test bin/rails db:seed:replant"

  if success?
    step "Signoff: All systems go. Ready for merge and deploy.", "gh signoff"
  else
    failure "Signoff: CI failed. Do not merge or deploy.", "Fix the issues and try again."
  end
end
