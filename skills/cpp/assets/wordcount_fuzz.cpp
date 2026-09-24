// libFuzzer target: ./acme_fuzz_wordcount -max_total_time=60 corpus/
#include <cstddef>
#include <cstdint>
#include <string_view>

#include "acme/wordcount/wordcount.hpp"

extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t* data, std::size_t size) {
  // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the fuzzer ABI hands us bytes
  const std::string_view text(reinterpret_cast<const char*>(data), size);
  acme::wordcount::Counter counter;
  if (counter.add(text, {.max_word_length = 64})) {
    (void)acme::wordcount::render(counter.top(5));
  }
  (void)acme::wordcount::parse_count(text);
  return 0;
}
