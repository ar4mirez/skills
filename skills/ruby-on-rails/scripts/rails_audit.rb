#!/usr/bin/env ruby
# frozen_string_literal: true

# Static health check of a Rails application directory (no boot, no gems).
#
# Usage:
#   ruby scripts/rails_audit.rb [APP_DIR] [--json] [--fail-on high|medium|low|none]
#
# Checks:
#   high    foreign-key columns without a leading index (db/schema.rb), rescue Exception,
#           save callbacks that re-save their own record (recursion),
#           params permit!
#   medium  side effects (mail, jobs, HTTP) in after_save/create/update callbacks,
#           non-RESTful routes (member/collection blocks) and controller actions,
#           app/services sprawl, domains without package.yml / Packwerk / packwerk-extensions,
#           default_scope, unscoped Model.find(params[...]) in controllers,
#           obsolete frontend gems (turbolinks, rails-ujs, webpacker)
#   low     fat models/controllers, update_attribute, legacy params.require.permit,
#           Date.today/Time.now, Redis-backed gems on Rails 8+ (Solid stack covers them)
#
# Exit codes: 0 = no findings at/above --fail-on (default: high), 1 = findings, 2 = bad input.
# Requires only Ruby 2.6+ standard library.

require "json"
require "optparse"

module RailsAudit
  RESTFUL_ACTIONS = %w[index show new create edit update destroy].freeze
  SEVERITIES = %w[high medium low].freeze
  REDIS_GEMS = %w[redis sidekiq resque delayed_job].freeze
  OBSOLETE_GEMS = { "turbolinks" => "use turbo-rails", "rails-ujs" => "use Turbo (data-turbo-method/confirm)",
                    "webpacker" => "use importmap-rails or jsbundling-rails",
                    "sprockets-rails" => "Rails 8 defaults to Propshaft" }.freeze
  FAT_MODEL_LINES = 100        # Sandi Metz: classes ≤ 100 lines
  FAT_CONTROLLER_LINES = 100

  Finding = Struct.new(:severity, :check, :location, :message) do
    def to_h
      { severity: severity, check: check, location: location, message: message }
    end
  end

  class Auditor
    attr_reader :root, :findings, :facts

    def initialize(root)
      @root = File.expand_path(root)
      @findings = []
      @facts = {}
    end

    def run
      detect_versions
      check_schema_indexes
      check_routes
      check_controllers
      check_services
      check_domains
      check_models
      check_code_smells
      check_gems
      self
    end

    private

    def add(severity, check, location, message)
      @findings << Finding.new(severity, check, location, message)
    end

    def path(*parts)
      File.join(root, *parts)
    end

    def rel(file)
      file.sub("#{root}/", "")
    end

    def ruby_files(dir)
      Dir.glob(path(dir, "**", "*.rb")).sort
    end

    def detect_versions
      lock = path("Gemfile.lock")
      if File.file?(lock)
        text = File.read(lock)
        rails = text[/^    rails \(([\d.]+)\)/, 1]
        @facts[:rails] = rails if rails
        @facts[:gems] = text.scan(/^    ([a-z0-9_\-]+) \(/).flatten.uniq
      end
      rv = path(".ruby-version")
      @facts[:ruby] = File.read(rv).strip if File.file?(rv)
    end

    def rails_major
      @facts[:rails].to_s.split(".").first.to_i
    end

    # --- db/schema.rb: every *_id column should lead some index ----------------
    def check_schema_indexes
      schema = path("db", "schema.rb")
      return unless File.file?(schema)

      table = nil
      columns = {}
      leading = Hash.new { |h, k| h[k] = [] }
      File.foreach(schema).with_index(1) do |line, lineno|
        if (m = line.match(/^\s*create_table "([^"]+)"/))
          table = m[1]
          columns[table] = []
        elsif table && (m = line.match(/^\s*t\.(?:bigint|integer|uuid|string) "([a-z0-9_]+_id)"/))
          columns[table] << [m[1], lineno]
        elsif table && (m = line.match(/^\s*t\.index \[([^\]]+)\]/))
          leading[table] << m[1].scan(/"([^"]+)"/).flatten
        elsif (m = line.match(/^\s*add_index "([^"]+)", \[([^\]]+)\]/))
          leading[m[1]] << m[2].scan(/"([^"]+)"/).flatten
        elsif (m = line.match(/^\s*add_index "([^"]+)", "([^"]+)"/))
          leading[m[1]] << [m[2]]
        elsif line =~ /^\s*end\s*$/ && line !~ /^\s{4,}/
          table = nil
        end
      end

      columns.each do |tbl, cols|
        cols.each do |(col, lineno)|
          prefix = col.sub(/_id\z/, "")
          covered = leading[tbl].any? do |idx|
            idx.first == col || (idx.first == "#{prefix}_type" && idx[1] == col)
          end
          next if covered

          add("high", "unindexed-foreign-key", "db/schema.rb:#{lineno}",
              "#{tbl}.#{col} has no index starting with it. Add `add_index :#{tbl}, :#{col}` " \
              "(algorithm: :concurrently on large Postgres tables).")
        end
      end
    end

    # --- routes: member/collection blocks mean custom actions ------------------
    def check_routes
      routes = path("config", "routes.rb")
      return unless File.file?(routes)

      File.foreach(routes).with_index(1) do |line, lineno|
        next if line.strip.start_with?("#")

        if line =~ /\b(member|collection)\s+do\b/ || line =~ /\bon:\s*:(member|collection)\b/
          add("medium", "non-restful-route", "config/routes.rb:#{lineno}",
              "`#{Regexp.last_match(1)}` route adds a custom action. Model the verb as a resource " \
              "(e.g. `resource :publication, only: %i[create destroy]`) with its own controller.")
        end
      end
    end

    # --- controllers: public non-REST actions, size, unscoped finds ------------
    def check_controllers
      ruby_files("app/controllers").each do |file|
        next if file.include?("/concerns/") || File.basename(file) == "application_controller.rb"

        lines = File.readlines(file)
        if lines.size > FAT_CONTROLLER_LINES
          add("low", "fat-controller", rel(file),
              "#{lines.size} lines (≤ 100). Controllers call one domain operation per action; split custom actions into resource controllers.")
        end

        visibility = :public
        lines.each_with_index do |line, i|
          visibility = :private if line =~ /^\s*(private|protected)\s*$/
          next unless visibility == :public

          m = line.match(/^\s*def\s+([a-z_][a-zA-Z0-9_]*[?!]?)/)
          next unless m
          next if RESTFUL_ACTIONS.include?(m[1])

          add("medium", "non-restful-action", "#{rel(file)}:#{i + 1}",
              "Public action `#{m[1]}` isn't one of the seven REST actions. Extract a resource " \
              "controller, or make it private if it's a helper.")
        end

        lines.each_with_index do |line, i|
          next unless line =~ /\b([A-Z][A-Za-z0-9:]*)\.find(?:_by)?[!(]?\s*\(?\s*params\b/

          add("medium", "unscoped-find", "#{rel(file)}:#{i + 1}",
              "`#{Regexp.last_match(1)}.find(params...)` isn't scoped to the current tenant. Use " \
              "`#{Regexp.last_match(1)}.where(account: Current.account).find(...)` (or policy_scope) and authorize with Pundit.")
        end
      end
    end

    # --- app/services: operations belong inside a domain -----------------------
    def check_services
      files = Dir.glob(path("app", "services", "**", "*.rb"))
      return if files.empty?

      add("medium", "services-directory", "app/services",
          "#{files.size} file(s). Move each into its bounded context as an operation: " \
          "app/domains/<domain>/operations/<verb_noun>.rb (e.g. Billing::PublishInvoice.call) returning ApplicationResult.")
    end

    # --- app/domains + Packwerk -------------------------------------------------
    def check_domains
      domains = Dir.glob(path("app", "domains", "*")).select { |d| File.directory?(d) }
      return if domains.empty?

      unless File.file?(path("packwerk.yml"))
        add("medium", "packwerk-missing", "packwerk.yml",
            "app/domains exists but Packwerk isn't configured. Boundaries aren't enforced: add packwerk + packwerk-extensions and run bin/packwerk init.")
      end
      domains.each do |dir|
        next if File.file?(File.join(dir, "package.yml"))

        add("medium", "domain-without-package", rel(dir),
            "Domain has no package.yml. Add one with enforce_dependencies, enforce_privacy and public_path (see assets/package.yml).")
      end
      privacy = Dir.glob(path("app", "domains", "*", "package.yml")).any? { |f| File.read(f) =~ /enforce_privacy:\s*true/ }
      if privacy && !(@facts[:gems] || []).include?("packwerk-extensions")
        add("medium", "privacy-not-enforced", "Gemfile.lock",
            "package.yml files set enforce_privacy, but packwerk-extensions isn't installed. Core Packwerk ignores privacy, so add the gem and `require: [packwerk-extensions]` in packwerk.yml.")
      end
    end

    # --- models ----------------------------------------------------------------
    def check_models
      ruby_files("app/models").each do |file|
        lines = File.readlines(file)
        if lines.size > FAT_MODEL_LINES
          add("low", "fat-model", rel(file),
              "#{lines.size} lines (Sandi Metz: ≤ 100). Keep models to data + invariants; move mutations into domain operations, queries into query objects.")
        end
        check_transaction_side_effects(file, lines)
        lines.each_with_index do |line, i|
          next unless line =~ /^\s*default_scope\b/

          add("medium", "default-scope", "#{rel(file)}:#{i + 1}",
              "default_scope leaks into associations and joins. Use a named scope and call it explicitly.")
        end
      end
    end

    SIDE_EFFECT = /deliver_now|deliver_later|perform_later|perform_now|Net::HTTP|HTTParty|Faraday|RestClient|Stripe::/.freeze

    # after_save/after_create/after_update run inside the transaction: side effects there
    # fire even when the transaction rolls back (and before other processes can see the row).
    def check_transaction_side_effects(file, lines)
      lines.each_with_index do |line, i|
        m = line.match(/^\s*(after_(?:save|create|update|destroy))\s+:([a-z_][a-zA-Z0-9_]*[?!]?)/)
        next unless m

        body = method_body(lines, m[2])
        if m[1] != "after_destroy" && body =~ /(?<![\w.])(update_attribute|update!?|save!?)\b|\bself\.(update_attribute|update!?|save!?)\b/
          add("high", "callback-recursion", "#{rel(file)}:#{i + 1}",
              "`#{m[1]} :#{m[2]}` calls `#{Regexp.last_match(1) || Regexp.last_match(2)}` on the same record, which runs the " \
              "callbacks again (infinite loop or repeated side effects). Set the attribute before saving, or use an explicit method.")
        end
        next unless body =~ SIDE_EFFECT

        add("medium", "side-effect-in-transaction", "#{rel(file)}:#{i + 1}",
            "`#{m[1]} :#{m[2]}` triggers #{Regexp.last_match(0)} inside the transaction. Use " \
            "#{m[1] == 'after_save' ? 'after_commit' : "#{m[1]}_commit"} (or move the side effect into a domain operation).")
      end
    end

    def method_body(lines, name)
      start = lines.index { |l| l =~ /^\s*def\s+#{Regexp.escape(name)}\b/ }
      return "" unless start

      rest = lines[(start + 1)..-1]
      stop = rest.index { |l| l =~ /^\s*(def\s|private\b|protected\b)/ } || rest.size
      rest[0...stop].join
    end

    # --- app-wide smells ---------------------------------------------------------
    def check_code_smells
      ruby_files("app").each do |file|
        File.foreach(file).with_index(1) do |line, lineno|
          code = line.sub(/#.*$/, "")
          loc = "#{rel(file)}:#{lineno}"
          if code =~ /rescue\s+Exception\b/
            add("high", "rescue-exception", loc, "`rescue Exception` also catches signals and exits. Rescue StandardError subclasses you expect.")
          end
          if code =~ /\.permit!/
            add("high", "permit-bang", loc, "`permit!` allows mass assignment of every attribute. Use `params.expect(model: [...])`.")
          end
          if code =~ /\bupdate_attribute\(/
            add("low", "update-attribute", loc, "`update_attribute` skips validations. Use `update!` (or `update_column` with a comment explaining why).")
          end
          if code =~ /params\.require\([^)]*\)\.permit\(/ && rails_major >= 8
            add("low", "legacy-strong-params", loc, "Rails 8: use `params.expect(...)`, which returns 400 on malformed input instead of 500.")
          end
          if code =~ /\b(Date\.today|Time\.now)\b/
            add("low", "time-zone", loc, "`#{Regexp.last_match(1)}` ignores the app time zone. Use `Date.current` / `Time.current`.")
          end
        end
      end
    end

    # --- Gemfile.lock --------------------------------------------------------------
    def check_gems
      gems = @facts[:gems] || []
      OBSOLETE_GEMS.each do |gem, fix|
        next unless gems.include?(gem)
        next if gem == "sprockets-rails" && rails_major < 8

        add(gem == "sprockets-rails" ? "low" : "medium", "obsolete-gem", "Gemfile.lock", "#{gem} is obsolete: #{fix}.")
      end
      return unless rails_major >= 8

      (REDIS_GEMS & gems).each do |gem|
        add("low", "redis-dependency", "Gemfile.lock",
            "#{gem}: Rails 8's Solid Queue/Cache/Cable remove the need for Redis unless you have proven scale needs.")
      end
    end
  end

  def self.report_text(auditor)
    out = []
    f = auditor.facts
    out << "Rails audit: #{auditor.root}"
    out << "Rails #{f[:rails] || '?'} · Ruby #{f[:ruby] || '?'}"
    if auditor.findings.empty?
      out << "No findings."
      return out.join("\n")
    end
    SEVERITIES.each do |sev|
      group = auditor.findings.select { |x| x.severity == sev }
      next if group.empty?

      out << ""
      out << "#{sev.upcase} (#{group.size})"
      group.each { |x| out << "  [#{x.check}] #{x.location}: #{x.message}" }
    end
    counts = SEVERITIES.map { |s| "#{auditor.findings.count { |x| x.severity == s }} #{s}" }.join(", ")
    out << ""
    out << "Summary: #{counts}"
    out.join("\n")
  end

  def self.main(argv)
    options = { json: false, fail_on: "high" }
    parser = OptionParser.new do |o|
      o.banner = "Usage: ruby scripts/rails_audit.rb [APP_DIR] [--json] [--fail-on high|medium|low|none]"
      o.separator ""
      o.separator "Static health check of a Rails app (schema indexes, REST, services, smells, gems)."
      o.separator "Examples:"
      o.separator "  ruby scripts/rails_audit.rb ."
      o.separator "  ruby scripts/rails_audit.rb ~/code/acme --json --fail-on medium"
      o.separator ""
      o.on("--json", "Print machine-readable JSON") { options[:json] = true }
      o.on("--fail-on LEVEL", %w[high medium low none], "Exit 1 at/above this severity (default: high)") { |v| options[:fail_on] = v }
      o.on("-h", "--help", "Show this help") { puts o; exit 0 }
    end
    begin
      args = parser.parse(argv)
    rescue OptionParser::ParseError => e
      warn "Error: #{e.message}\n#{parser.banner}"
      return 2
    end

    root = args.first || "."
    unless File.directory?(root) && (File.file?(File.join(root, "config", "application.rb")) || File.directory?(File.join(root, "app")))
      warn "Error: '#{root}' doesn't look like a Rails app (expected config/application.rb or app/). Pass the app root."
      return 2
    end

    auditor = Auditor.new(root).run
    if options[:json]
      puts JSON.pretty_generate(facts: auditor.facts.reject { |k, _| k == :gems }, findings: auditor.findings.map(&:to_h))
    else
      puts report_text(auditor)
    end

    return 0 if options[:fail_on] == "none"

    threshold = SEVERITIES.index(options[:fail_on])
    auditor.findings.any? { |x| SEVERITIES.index(x.severity) <= threshold } ? 1 : 0
  end
end

exit RailsAudit.main(ARGV) if $PROGRAM_NAME == __FILE__
