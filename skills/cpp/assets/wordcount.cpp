#include "acme/wordcount/wordcount.hpp"

#include <algorithm>
#include <charconv>
#include <format>
#include <iterator>
#include <ranges>
#include <system_error>

namespace acme::wordcount {
namespace {

[[nodiscard]] constexpr bool is_word_char(char c) noexcept {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '\'';
}

[[nodiscard]] constexpr char to_lower(char c) noexcept {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

struct Span {
  std::size_t begin;
  std::size_t end;
};

// Splits into word spans without allocating; validation happens before mutation.
[[nodiscard]] std::expected<std::vector<Span>, Error> tokenize(std::string_view text,
                                                               Limits limits) {
  std::vector<Span> spans;
  std::size_t i = 0;
  while (i < text.size()) {
    while (i < text.size() && !is_word_char(text[i])) {
      ++i;
    }
    const std::size_t begin = i;
    while (i < text.size() && is_word_char(text[i])) {
      ++i;
    }
    if (i == begin) {
      continue;
    }
    if (i - begin > limits.max_word_length) {
      return std::unexpected(Error{.code = ErrorCode::word_too_long, .offset = begin});
    }
    spans.push_back({.begin = begin, .end = i});
  }
  return spans;
}

}  // namespace

std::string Error::message() const {
  switch (code) {
    case ErrorCode::not_a_number:
      return std::format("not a number at offset {}", offset);
    case ErrorCode::out_of_range:
      return std::format("number out of range at offset {}", offset);
    case ErrorCode::word_too_long:
      return std::format("word too long at offset {}", offset);
  }
  return "unknown error";
}

std::expected<void, Error> Counter::add(std::string_view text, Limits limits) {
  auto spans = tokenize(text, limits);
  if (!spans) {
    return std::unexpected(spans.error());
  }
  std::string word;
  for (const auto [begin, end] : *spans) {
    word.assign(text.substr(begin, end - begin));
    std::ranges::transform(word, word.begin(), to_lower);
    ++counts_[word];
    ++total_;
  }
  return {};
}

void Counter::merge(const Counter& other) {
  for (const auto& [word, n] : other.counts_) {
    counts_[word] += n;
  }
  total_ += other.total_;
}

std::size_t Counter::count(std::string_view word) const {
  const auto it = counts_.find(word);  // heterogeneous lookup: no temporary string
  return it == counts_.end() ? 0 : it->second;
}

std::vector<WordCount> Counter::top(std::size_t n) const {
  std::vector<WordCount> rows;
  rows.reserve(counts_.size());
  for (const auto& [word, count] : counts_) {
    rows.push_back({.word = word, .count = count});
  }
  const auto by_count_then_word = [](const WordCount& a, const WordCount& b) {
    return a.count != b.count ? a.count > b.count : a.word < b.word;
  };
  const auto keep = std::min(n, rows.size());
  std::ranges::partial_sort(rows, rows.begin() + static_cast<std::ptrdiff_t>(keep),
                            by_count_then_word);
  rows.resize(keep);
  return rows;
}

std::expected<std::size_t, Error> parse_count(std::string_view text) {
  std::size_t value = 0;
  const auto* first = text.data();
  const auto* last = text.data() + text.size();
  const auto [ptr, ec] = std::from_chars(first, last, value);
  if (ec == std::errc::result_out_of_range || (ec == std::errc{} && ptr == last && value == 0)) {
    return std::unexpected(Error{.code = ErrorCode::out_of_range, .offset = 0});
  }
  if (ec != std::errc{} || ptr != last) {
    return std::unexpected(
        Error{.code = ErrorCode::not_a_number, .offset = static_cast<std::size_t>(ptr - first)});
  }
  return value;
}

std::string render(const std::vector<WordCount>& rows) {
  std::string out;
  for (const auto& row : rows) {
    std::format_to(std::back_inserter(out), "{} {}\n", row.word, row.count);
  }
  return out;
}

}  // namespace acme::wordcount
