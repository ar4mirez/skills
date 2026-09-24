#include "acme/wordcount/thread_pool.hpp"

#include <atomic>
#include <future>
#include <memory>
#include <stdexcept>
#include <vector>

#include <gtest/gtest.h>

TEST(ThreadPool, RunsAllTasksAndReturnsResults) {
  acme::ThreadPool pool(4);
  std::vector<std::future<int>> results;
  results.reserve(100);
  for (int i = 0; i < 100; ++i) {
    results.push_back(pool.submit([i] { return i * i; }));
  }
  long sum = 0;
  for (auto& r : results) {
    sum += r.get();
  }
  EXPECT_EQ(sum, 328350);
}

TEST(ThreadPool, AcceptsMoveOnlyCallables) {
  acme::ThreadPool pool(1);
  auto value = std::make_unique<int>(7);
  auto result = pool.submit([v = std::move(value)] { return *v; });
  EXPECT_EQ(result.get(), 7);
}

TEST(ThreadPool, PropagatesExceptionsThroughFuture) {
  acme::ThreadPool pool(1);
  auto result = pool.submit([]() -> int { throw std::runtime_error("boom"); });
  EXPECT_THROW((void)result.get(), std::runtime_error);
}

TEST(ThreadPool, DrainsQueueOnDestruction) {
  std::atomic<int> done{0};
  {
    acme::ThreadPool pool(2);
    for (int i = 0; i < 50; ++i) {
      (void)pool.submit([&done] { done.fetch_add(1, std::memory_order_relaxed); });
    }
  }
  EXPECT_EQ(done.load(), 50);
}
