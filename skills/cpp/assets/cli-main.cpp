// wc: count words across files in parallel and print the most frequent ones.
//   wc [--top N] FILE...
// Exit codes: 0 ok, 1 runtime failure (unreadable file, oversized word), 2 bad usage.
#include <cstddef>
#include <cstdio>
#include <exception>
#include <expected>
#include <fstream>
#include <future>
#include <iterator>
#include <print>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "acme/wordcount/thread_pool.hpp"
#include "acme/wordcount/wordcount.hpp"

namespace {

namespace wc = acme::wordcount;

struct Options {
  std::size_t top = 10;
  std::vector<std::string> files;
};

constexpr int kExitOk = 0;
constexpr int kExitFailure = 1;
constexpr int kExitUsage = 2;

void usage(std::FILE* out) { std::println(out, "usage: wc [--top N] FILE..."); }

std::expected<Options, std::string> parse_args(std::span<char*> args) {
  Options opts;
  for (std::size_t i = 1; i < args.size(); ++i) {
    const std::string_view arg = args[i];
    if (arg == "--top") {
      if (i + 1 >= args.size()) {
        return std::unexpected("--top needs a value");
      }
      auto n = wc::parse_count(args[++i]);
      if (!n) {
        return std::unexpected("--top: " + n.error().message());
      }
      opts.top = *n;
    } else if (arg.starts_with("-")) {
      return std::unexpected("unknown option " + std::string(arg));
    } else {
      opts.files.emplace_back(arg);
    }
  }
  if (opts.files.empty()) {
    return std::unexpected("no input files");
  }
  return opts;
}

std::expected<wc::Counter, std::string> count_file(const std::string& path) {
  std::ifstream in(path, std::ios::binary);
  if (!in) {
    return std::unexpected(path + ": cannot open");
  }
  const std::string text{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
  wc::Counter counter;
  if (auto added = counter.add(text); !added) {
    return std::unexpected(path + ": " + added.error().message());
  }
  return counter;
}

int run(const Options& opts) {
  acme::ThreadPool pool;
  std::vector<std::future<std::expected<wc::Counter, std::string>>> jobs;
  jobs.reserve(opts.files.size());
  for (const auto& file : opts.files) {
    jobs.push_back(pool.submit([&file] { return count_file(file); }));
  }
  wc::Counter total;
  int status = kExitOk;
  for (auto& job : jobs) {
    auto result = job.get();
    if (!result) {
      std::println(stderr, "wc: {}", result.error());
      status = kExitFailure;
      continue;
    }
    total.merge(*result);
  }
  std::print("{}", wc::render(total.top(opts.top)));
  return status;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    auto opts = parse_args(std::span(argv, static_cast<std::size_t>(argc)));
    if (!opts) {
      std::println(stderr, "wc: {}", opts.error());
      usage(stderr);
      return kExitUsage;
    }
    return run(*opts);
  } catch (const std::exception& e) {  // the one catch-all: at the process boundary
    // fputs, not println: formatting can throw, and nothing may escape main.
    (void)std::fputs("wc: fatal: ", stderr);
    (void)std::fputs(e.what(), stderr);
    (void)std::fputc('\n', stderr);
    return kExitFailure;
  } catch (...) {
    (void)std::fputs("wc: fatal: unknown exception\n", stderr);
    return kExitFailure;
  }
}
