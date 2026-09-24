/* kvstore-server: serve a read-only kvstore over HTTP/1.1 (POSIX).
 *
 *   PORT          listen port (default 8080)
 *   KVSTORE_FILE  key=value file loaded at startup (optional)
 *   WORKERS       worker threads, 1..64 (default 4)
 *
 * Design: the store is built once, then only read, so workers share it with
 * no locks. Each worker polls the shared listening socket and accepts; the
 * main thread waits for SIGINT/SIGTERM with sigwait() and flips an atomic
 * flag. No work happens in a signal handler. TLS, HTTP/2 and rate limiting
 * belong to the proxy in front (kamal-proxy, Cloudflare).
 *
 * Built with -D_POSIX_C_SOURCE=200809L (from CMake): with C_EXTENSIONS OFF,
 * glibc hides POSIX declarations unless a feature-test macro asks for them. */

#include "http_handler.h"
#include "kvstore/kvstore.h"

#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>

enum { MAX_WORKERS = 64, REQ_MAX = 8192, RESP_MAX = 4096 };

static atomic_bool stopping = false;

typedef struct server {
    const kvstore *kv; /* read-only after startup */
    int listen_fd;
} server;

/* Parses a decimal env var into [lo, hi]; returns fallback when unset. */
static bool env_long(const char *name, long lo, long hi, long fallback, long *out) {
    const char *s = getenv(name);
    if (!s || !*s) {
        *out = fallback;
        return true;
    }
    char *end = nullptr;
    errno = 0; /* strtol reports overflow only through errno */
    long v = strtol(s, &end, 10);
    if (errno != 0 || *end != '\0' || v < lo || v > hi) {
        fprintf(stderr, "kvstore-server: %s must be an integer in [%ld, %ld]\n", name, lo, hi);
        return false;
    }
    *out = v;
    return true;
}

static void set_nonblocking(int fd, bool on) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) {
        (void)fcntl(fd, F_SETFL, on ? flags | O_NONBLOCK : flags & ~O_NONBLOCK);
    }
}

static void handle_conn(const kvstore *kv, int fd) {
    set_nonblocking(fd, false); /* BSD/macOS: accepted sockets inherit O_NONBLOCK */
    struct timeval tv = {.tv_sec = 5};
    (void)setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    (void)setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);

    char req[REQ_MAX];
    size_t len = 0;
    while (len < sizeof req) {
        ssize_t n = recv(fd, req + len, sizeof req - len, 0);
        if (n <= 0) {
            break; /* EOF, timeout or error: answer with what we have */
        }
        len += (size_t)n;
        if (memchr(req, '\n', len)) {
            break; /* the request line is all we route on */
        }
    }
    char resp[RESP_MAX];
    size_t out = http_handle(kv, req, len, resp, sizeof resp);
    for (size_t sent = 0; sent < out;) {
        ssize_t n = send(fd, resp + sent, out - sent, 0);
        if (n <= 0) {
            break;
        }
        sent += (size_t)n;
    }
    close(fd);
}

static void *worker(void *arg) {
    const server *srv = arg;
    while (!atomic_load(&stopping)) {
        struct pollfd p = {.fd = srv->listen_fd, .events = POLLIN};
        int ready = poll(&p, 1, 250); /* wake up regularly to see `stopping` */
        if (ready <= 0) {
            continue;
        }
        int fd = accept(srv->listen_fd, nullptr, nullptr);
        if (fd < 0) {
            continue; /* another worker won the race, or a transient error */
        }
        handle_conn(srv->kv, fd);
    }
    return nullptr;
}

static int open_listener(long port) {
    int fd = socket(AF_INET6, SOCK_STREAM, 0);
    if (fd < 0) {
        return -1;
    }
    int on = 1;
    int off = 0;
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
    (void)setsockopt(fd, IPPROTO_IPV6, IPV6_V6ONLY, &off, sizeof off); /* v4 too */
    struct sockaddr_in6 addr = {
        .sin6_family = AF_INET6, .sin6_port = htons((uint16_t)port), .sin6_addr = IN6ADDR_ANY_INIT};
    if (bind(fd, (struct sockaddr *)&addr, sizeof addr) != 0 || listen(fd, 128) != 0) {
        close(fd);
        return -1;
    }
    /* Non-blocking, so a worker that loses the accept race goes back to poll
     * instead of blocking in accept() past shutdown. */
    set_nonblocking(fd, true);
    return fd;
}

static kvstore_status load_store(kvstore *kv, const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "kvstore-server: %s: %s\n", path, strerror(errno));
        return KVSTORE_ERR_INVALID;
    }
    static char buf[1u << 20];
    size_t len = fread(buf, 1, sizeof buf, f);
    bool too_big = len == sizeof buf;
    fclose(f);
    if (too_big) {
        fprintf(stderr, "kvstore-server: %s: larger than %zu bytes\n", path, sizeof buf);
        return KVSTORE_ERR_INVALID;
    }
    size_t line = 0;
    kvstore_status st = kvstore_parse(kv, buf, len, &line);
    if (st != KVSTORE_OK) {
        fprintf(stderr, "kvstore-server: %s:%zu: %s\n", path, line, kvstore_status_str(st));
    }
    return st;
}

int main(void) {
    long port = 0;
    long workers = 0;
    if (!env_long("PORT", 1, 65535, 8080, &port) ||
        !env_long("WORKERS", 1, MAX_WORKERS, 4, &workers)) {
        return 2;
    }

    kvstore *kv = nullptr;
    if (kvstore_create(&kv) != KVSTORE_OK) {
        fputs("kvstore-server: out of memory\n", stderr);
        return 1;
    }
    const char *path = getenv("KVSTORE_FILE");
    if (path && *path && load_store(kv, path) != KVSTORE_OK) {
        kvstore_destroy(kv);
        return 2;
    }

    /* Block the signals before creating threads so every thread inherits the
     * mask and only sigwait() below receives them. */
    sigset_t sigs;
    sigemptyset(&sigs);
    sigaddset(&sigs, SIGINT);
    sigaddset(&sigs, SIGTERM);
    pthread_sigmask(SIG_BLOCK, &sigs, nullptr);
    signal(SIGPIPE, SIG_IGN); /* a client closing early must not kill us */

    int rc = 0;
    server srv = {.kv = kv, .listen_fd = open_listener(port)};
    if (srv.listen_fd < 0) {
        fprintf(stderr, "kvstore-server: listen on %ld: %s\n", port, strerror(errno));
        kvstore_destroy(kv);
        return 1;
    }
    pthread_t threads[MAX_WORKERS];
    long started = 0;
    for (; started < workers; started++) {
        if (pthread_create(&threads[started], nullptr, worker, &srv) != 0) {
            rc = 1;
            break;
        }
    }
    if (rc == 0) {
        fprintf(stderr, "kvstore-server: listening on :%ld with %ld workers, %zu keys\n", port,
                workers, kvstore_count(kv));
        int sig = 0;
        sigwait(&sigs, &sig);
    }
    atomic_store(&stopping, true);
    for (long i = 0; i < started; i++) {
        pthread_join(threads[i], nullptr);
    }
    close(srv.listen_fd);
    kvstore_destroy(kv);
    return rc;
}
