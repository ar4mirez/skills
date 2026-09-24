#!/usr/bin/env ruby
# frozen_string_literal: true

# Validate a Hotwire Native path configuration JSON file.
#
# Usage:
#   ruby scripts/check_path_config.rb FILE.json [--platform ios|android|any] [--json]
#
# Errors (exit 1): invalid JSON; missing/invalid "settings" or "rules"; rules without
#   "patterns"/"properties"; invalid regex patterns; invalid values for known properties.
# Warnings: first rule isn't a ".*" catch-all; pull-to-refresh enabled on modals;
#   modal_style without context "modal"; platform-specific keys used on the other platform;
#   Android rules without "uri"; file name without a version suffix (e.g. ios_v1.json).
#
# Reference: https://native.hotwired.dev/reference/path-configuration
# Exit codes: 0 = valid, 1 = errors, 2 = bad invocation. Ruby 2.6+ stdlib only.

require "json"
require "optparse"

module PathConfigCheck
  COMMON = {
    "context" => %w[default modal],
    "presentation" => %w[default push pop replace replace_root clear_all refresh none],
    "pull_to_refresh_enabled" => [true, false],
    "animated" => [true, false]
  }.freeze
  IOS = {
    "view_controller" => :string,
    "modal_style" => %w[large medium full page_sheet form_sheet],
    "modal_dismiss_gesture_enabled" => [true, false]
  }.freeze
  ANDROID = { "uri" => :string, "fallback_uri" => :string, "title" => :string }.freeze

  def self.check(data, platform:, filename:)
    errors = []
    warnings = []

    unless data.is_a?(Hash)
      return { errors: ["Top level must be a JSON object with \"settings\" and \"rules\"."], warnings: [] }
    end

    errors << "Missing \"settings\" object (use {} if empty)." unless data.key?("settings")
    errors << "\"settings\" must be an object." if data.key?("settings") && !data["settings"].is_a?(Hash)
    rules = data["rules"]
    if !data.key?("rules")
      errors << "Missing \"rules\" array (use [] if empty)."
      rules = []
    elsif !rules.is_a?(Array)
      errors << "\"rules\" must be an array."
      rules = []
    end

    rules.each_with_index do |rule, i|
      where = "rules[#{i}]"
      unless rule.is_a?(Hash)
        errors << "#{where} must be an object with \"patterns\" and \"properties\"."
        next
      end

      patterns = rule["patterns"]
      if patterns.is_a?(String)
        warnings << "#{where}.patterns is a string; use an array of regex strings."
        patterns = [patterns]
      end
      if !patterns.is_a?(Array) || patterns.empty?
        errors << "#{where}.patterns must be a non-empty array of regex strings."
      else
        patterns.each do |pat|
          unless pat.is_a?(String)
            errors << "#{where}.patterns contains a non-string: #{pat.inspect}."
            next
          end
          begin
            Regexp.new(pat)
          rescue RegexpError => e
            errors << "#{where}: invalid regex #{pat.inspect} (#{e.message})."
          end
        end
      end

      props = rule["properties"]
      unless props.is_a?(Hash)
        errors << "#{where}.properties must be an object."
        next
      end

      known = COMMON.merge(IOS).merge(ANDROID)
      props.each do |key, value|
        allowed = known[key]
        next unless allowed

        if allowed == :string
          errors << "#{where}.properties.#{key} must be a string." unless value.is_a?(String)
        elsif !allowed.include?(value)
          errors << "#{where}.properties.#{key} = #{value.inspect} is invalid; expected one of #{allowed.map(&:to_s).join(', ')}."
        end
      end

      if props["context"] == "modal" && props["pull_to_refresh_enabled"] == true
        warnings << "#{where}: pull-to-refresh on a modal conflicts with the dismiss gesture and can wipe form input."
      end
      if props.key?("modal_style") && props["context"] != "modal"
        warnings << "#{where}: modal_style only applies when context is \"modal\"."
      end
      if platform == "ios" && (props.keys & ANDROID.keys).any?
        warnings << "#{where}: Android-only keys (#{(props.keys & ANDROID.keys).join(', ')}) in an iOS config."
      end
      if platform == "android" && (props.keys & IOS.keys).any?
        warnings << "#{where}: iOS-only keys (#{(props.keys & IOS.keys).join(', ')}) in an Android config."
      end
    end

    first = rules.first
    if first.is_a?(Hash) && !Array(first["patterns"]).include?(".*")
      warnings << "First rule should be a \".*\" catch-all that sets defaults; later rules override it."
    end
    if platform == "android" && rules.any? && rules.none? { |r| r.is_a?(Hash) && r["properties"].is_a?(Hash) && r["properties"]["uri"] }
      warnings << "No rule sets \"uri\" (e.g. \"hotwire://fragment/web\"); Android needs it to map destinations."
    end
    if filename && File.basename(filename) !~ /_v\d+\.json\z/
      warnings << "Version the file name (e.g. ios_v1.json, android_v1.json) so new app builds can move to _v2 without breaking old ones."
    end

    { errors: errors, warnings: warnings }
  end

  def self.main(argv)
    options = { platform: "any", json: false }
    parser = OptionParser.new do |o|
      o.banner = "Usage: ruby scripts/check_path_config.rb FILE.json [--platform ios|android|any] [--json]"
      o.separator ""
      o.separator "Validate a Hotwire Native path configuration."
      o.separator "Examples:"
      o.separator "  ruby scripts/check_path_config.rb public/configurations/ios_v1.json --platform ios"
      o.separator "  ruby scripts/check_path_config.rb assets/path-configuration.json"
      o.separator ""
      o.on("--platform NAME", %w[ios android any], "Platform-specific checks (default: any)") { |v| options[:platform] = v }
      o.on("--json", "Print machine-readable JSON") { options[:json] = true }
      o.on("-h", "--help", "Show this help") { puts o; exit 0 }
    end
    begin
      args = parser.parse(argv)
    rescue OptionParser::ParseError => e
      warn "Error: #{e.message}\n#{parser.banner}"
      return 2
    end
    file = args.first
    unless file
      warn "Error: pass a path configuration JSON file.\n#{parser.banner}"
      return 2
    end

    begin
      data = JSON.parse(File.read(file))
    rescue Errno::ENOENT
      warn "Error: '#{file}' not found."
      return 2
    rescue JSON::ParserError => e
      result = { errors: ["Invalid JSON: #{e.message.lines.first.strip}"], warnings: [] }
    end
    result ||= check(data, platform: options[:platform], filename: file)

    if options[:json]
      puts JSON.pretty_generate(result.merge(ok: result[:errors].empty?))
    else
      result[:errors].each { |m| puts "ERROR: #{m}" }
      result[:warnings].each { |m| puts "WARN:  #{m}" }
      puts(result[:errors].empty? ? "OK: #{file} is a valid path configuration#{result[:warnings].empty? ? '' : ' (with warnings)'}." : "#{result[:errors].size} error(s) in #{file}.")
    end
    result[:errors].empty? ? 0 : 1
  end
end

exit PathConfigCheck.main(ARGV) if $PROGRAM_NAME == __FILE__
