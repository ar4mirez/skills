#include <cstdint>
#include <string>

#include <benchmark/benchmark.h>

#include "acme/wordcount/wordcount.hpp"

namespace {

void BM_CounterAdd(benchmark::State& state) {
  std::string text;
  for (int i = 0; i < 1000; ++i) {
    text += "lorem ipsum dolor sit amet ";
  }
  for (auto _ : state) {
    acme::wordcount::Counter counter;
    benchmark::DoNotOptimize(counter.add(text));
  }
  state.SetBytesProcessed(state.iterations() * static_cast<std::int64_t>(text.size()));
}
BENCHMARK(BM_CounterAdd);

}  // namespace
