#pragma once

#include <algorithm>
#include <concepts>
#include <condition_variable>
#include <cstddef>
#include <functional>
#include <future>
#include <mutex>
#include <queue>
#include <stop_token>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>

namespace acme {

// Fixed-size pool of std::jthread workers. Rule of Zero: the jthreads' destructors
// request stop and join, and condition_variable_any wakes on stop, so no
// hand-written destructor is needed. Queued work is drained before workers exit.
// The mutex member makes the pool non-copyable and non-movable, which the
// workers' captured `this` requires.
class ThreadPool {
 public:
  explicit ThreadPool(std::size_t threads = std::max(1U, std::thread::hardware_concurrency())) {
    workers_.reserve(threads);
    for (std::size_t i = 0; i < threads; ++i) {
      workers_.emplace_back([this](const std::stop_token& stop) { run(stop); });
    }
  }

  template <class F>
    requires std::invocable<F&>
  [[nodiscard]] auto submit(F&& fn) -> std::future<std::invoke_result_t<F&>> {
    using R = std::invoke_result_t<F&>;
    std::packaged_task<R()> task(std::forward<F>(fn));
    auto result = task.get_future();
    {
      const std::scoped_lock lock(mutex_);
      // packaged_task<void()> accepts move-only callables; std::function does not.
      queue_.emplace([t = std::move(task)]() mutable { t(); });
    }
    ready_.notify_one();
    return result;
  }

  [[nodiscard]] std::size_t size() const noexcept { return workers_.size(); }

 private:
  void run(const std::stop_token& stop) {
    while (true) {
      std::packaged_task<void()> task;
      {
        std::unique_lock lock(mutex_);
        // Returns false only when stop was requested AND the queue is empty.
        if (!ready_.wait(lock, stop, [this] { return !queue_.empty(); })) {
          return;
        }
        task = std::move(queue_.front());
        queue_.pop();
      }
      task();  // exceptions are captured in the future, never escape the worker
    }
  }

  std::mutex mutex_;
  std::condition_variable_any ready_;
  std::queue<std::packaged_task<void()>> queue_;
  // Declared last so it's destroyed first: workers join before the queue,
  // mutex, and condition variable they use go away.
  std::vector<std::jthread> workers_;
};

}  // namespace acme
