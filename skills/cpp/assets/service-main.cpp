// wc-server: HTTP front end for the word counter.
//   GET  /up                 -> 200 "ok" (kamal-proxy health check)
//   POST /count?top=N  body  -> 200 "word count" lines, 400/413 on bad input
// Configuration: PORT (default 8080). Stops cleanly on SIGTERM/SIGINT.
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <print>
#include <string>
#include <string_view>
#include <thread>

#include <httplib.h>
#include <pthread.h>
#include <sys/socket.h>
#include <unistd.h>

#include "acme/wordcount/wordcount.hpp"

namespace {

namespace wc = acme::wordcount;

constexpr std::size_t kMaxBodyBytes = std::size_t{1024} * 1024;
constexpr std::size_t kDefaultTop = 10;

int port_from_env() {
  const char* raw = std::getenv("PORT");  // NOLINT(concurrency-mt-unsafe): read once at startup
  if (raw == nullptr) {
    return 8080;
  }
  auto parsed = wc::parse_count(raw);
  if (!parsed || *parsed > 65535) {
    std::println(stderr, "wc-server: invalid PORT '{}', using 8080", raw);
    return 8080;
  }
  return static_cast<int>(*parsed);
}

void handle_count(const httplib::Request& req, httplib::Response& res) {
  std::size_t top = kDefaultTop;
  if (req.has_param("top")) {
    auto parsed = wc::parse_count(req.get_param_value("top"));
    if (!parsed) {
      res.status = httplib::StatusCode::BadRequest_400;
      res.set_content("top: " + parsed.error().message() + "\n", "text/plain");
      return;
    }
    top = *parsed;
  }
  wc::Counter counter;
  if (auto added = counter.add(req.body); !added) {
    res.status = httplib::StatusCode::BadRequest_400;
    res.set_content(added.error().message() + "\n", "text/plain");
    return;
  }
  res.set_content(wc::render(counter.top(top)), "text/plain");
}

}  // namespace

int main() {
  try {
    // Block SIGTERM/SIGINT in every thread (the mask is inherited), then wait
    // for them synchronously on one thread. A classic signal handler can't
    // safely call Server::stop(): it isn't async-signal-safe.
    sigset_t signals{};
    sigemptyset(&signals);
    sigaddset(&signals, SIGTERM);
    sigaddset(&signals, SIGINT);
    pthread_sigmask(SIG_BLOCK, &signals, nullptr);

    httplib::Server server;
    server.set_payload_max_length(kMaxBodyBytes);
    // httplib's default adds SO_REUSEPORT, which lets a second instance silently
    // share the port. Keep only SO_REUSEADDR (fast restarts).
    server.set_socket_options([](socket_t sock) {
      const int yes = 1;
      setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    });
    server.Get("/up", [](const httplib::Request&, httplib::Response& res) {
      res.set_content("ok", "text/plain");
    });
    server.Post("/count", handle_count);

    const std::jthread stopper([&server, &signals] {
      int received = 0;
      sigwait(&signals, &received);
      std::println(stderr, "wc-server: signal {}, shutting down", received);
      server.stop();
    });

    const int port = port_from_env();
    if (!server.bind_to_port("0.0.0.0", port)) {
      std::println(stderr, "wc-server: cannot bind :{}", port);
      kill(getpid(), SIGTERM);  // wake the stopper so its jthread can join
      return 1;
    }
    std::println(stderr, "wc-server: listening on :{}", port);
    if (!server.listen_after_bind()) {
      std::println(stderr, "wc-server: listen failed");
      kill(getpid(), SIGTERM);
      return 1;
    }
    return 0;
  } catch (const std::exception& e) {  // the one catch-all: at the process boundary
    // fputs, not println: formatting can throw, and nothing may escape main.
    (void)std::fputs("wc-server: fatal: ", stderr);
    (void)std::fputs(e.what(), stderr);
    (void)std::fputc('\n', stderr);
    return 1;
  } catch (...) {
    (void)std::fputs("wc-server: fatal: unknown exception\n", stderr);
    return 1;
  }
}
