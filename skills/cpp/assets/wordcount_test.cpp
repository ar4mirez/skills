#include "acme/wordcount/wordcount.hpp"

#include <string>
#include <vector>

#include <gtest/gtest.h>

namespace wc = acme::wordcount;

TEST(Counter, CountsCaseInsensitively) {
  wc::Counter counter;
  ASSERT_TRUE(counter.add("The cat, the HAT; the end."));
  EXPECT_EQ(counter.count("the"), 3U);
  EXPECT_EQ(counter.count("cat"), 1U);
  EXPECT_EQ(counter.count("dog"), 0U);
  EXPECT_EQ(counter.total(), 6U);
  EXPECT_EQ(counter.unique(), 4U);
}

TEST(Counter, TopBreaksTiesAlphabetically) {
  wc::Counter counter;
  ASSERT_TRUE(counter.add("b a c b a"));
  const std::vector<wc::WordCount> expected{{.word = "a", .count = 2}, {.word = "b", .count = 2}};
  EXPECT_EQ(counter.top(2), expected);
  EXPECT_EQ(counter.top(100).size(), 3U);
  EXPECT_TRUE(counter.top(0).empty());
}

TEST(Counter, RejectsOversizedWordWithoutPartialUpdate) {
  wc::Counter counter;
  const std::string text = "ok " + std::string(10, 'x');
  const auto result = counter.add(text, {.max_word_length = 5});
  ASSERT_FALSE(result);
  EXPECT_EQ(result.error().code, wc::ErrorCode::word_too_long);
  EXPECT_EQ(result.error().offset, 3U);
  EXPECT_EQ(counter.total(), 0U);
}

TEST(Counter, MergeAddsCounts) {
  wc::Counter a;
  wc::Counter b;
  ASSERT_TRUE(a.add("x y"));
  ASSERT_TRUE(b.add("y z"));
  a.merge(b);
  EXPECT_EQ(a.count("y"), 2U);
  EXPECT_EQ(a.total(), 4U);
}

TEST(Counter, EmptyInputIsFine) {
  wc::Counter counter;
  EXPECT_TRUE(counter.add(""));
  EXPECT_TRUE(counter.add(" ,.;\n"));
  EXPECT_EQ(counter.total(), 0U);
}

TEST(ParseCount, AcceptsPositiveIntegers) { EXPECT_EQ(wc::parse_count("42"), 42U); }

TEST(ParseCount, RejectsGarbage) {
  for (const auto* bad : {"", "-1", "12x", " 1", "abc"}) {
    const auto result = wc::parse_count(bad);
    ASSERT_FALSE(result) << bad;
    EXPECT_EQ(result.error().code, wc::ErrorCode::not_a_number) << bad;
  }
}

TEST(ParseCount, RejectsZeroAndOverflow) {
  for (const auto* bad : {"0", "999999999999999999999999"}) {
    const auto result = wc::parse_count(bad);
    ASSERT_FALSE(result) << bad;
    EXPECT_EQ(result.error().code, wc::ErrorCode::out_of_range) << bad;
  }
}

TEST(Render, FormatsLines) {
  EXPECT_EQ(wc::render({{.word = "a", .count = 2}, {.word = "b", .count = 1}}), "a 2\nb 1\n");
}
