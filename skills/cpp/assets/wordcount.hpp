#pragma once

#include <cstddef>
#include <cstdint>
#include <expected>
#include <functional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace acme::wordcount {

enum class ErrorCode : std::uint8_t {
  not_a_number,
  out_of_range,
  word_too_long,
};

struct Error {
  ErrorCode code;
  std::size_t offset = 0;  // byte offset into the input where the problem starts

  [[nodiscard]] std::string message() const;
};

struct Limits {
  std::size_t max_word_length = 256;
};

struct WordCount {
  std::string word;
  std::size_t count = 0;

  friend bool operator==(const WordCount&, const WordCount&) = default;
};

// Transparent hash so find(std::string_view) doesn't allocate a std::string.
struct StringHash {
  using is_transparent = void;
  [[nodiscard]] std::size_t operator()(std::string_view s) const noexcept {
    return std::hash<std::string_view>{}(s);
  }
};

// Value type, Rule of Zero: copy, move, and destruction are all compiler-generated.
class Counter {
 public:
  // Counts lowercase ASCII words in `text`. Fails without partial updates if a
  // word exceeds the limit.
  [[nodiscard]] std::expected<void, Error> add(std::string_view text, Limits limits = {});

  void merge(const Counter& other);

  [[nodiscard]] std::size_t count(std::string_view word) const;
  [[nodiscard]] std::size_t total() const noexcept { return total_; }
  [[nodiscard]] std::size_t unique() const noexcept { return counts_.size(); }

  // The n most frequent words, ties broken alphabetically (deterministic output).
  [[nodiscard]] std::vector<WordCount> top(std::size_t n) const;

 private:
  std::unordered_map<std::string, std::size_t, StringHash, std::equal_to<>> counts_;
  std::size_t total_ = 0;
};

// Parses a positive count such as the CLI's `--top 10` argument.
[[nodiscard]] std::expected<std::size_t, Error> parse_count(std::string_view text);

// Renders `word count` lines; transport-agnostic so the CLI and the service share it.
[[nodiscard]] std::string render(const std::vector<WordCount>& rows);

}  // namespace acme::wordcount
