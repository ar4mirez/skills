#include "http_handler.h"
#include "kvstore/kvstore.h"
#include "test.h"

#include <string.h>

static kvstore *fixture(void) {
    kvstore *kv = nullptr;
    if (kvstore_create(&kv) != KVSTORE_OK || kvstore_set(kv, "greeting", "hello") != KVSTORE_OK) {
        kvstore_destroy(kv);
        return nullptr;
    }
    return kv;
}

static bool starts_with(const char *s, size_t len, const char *prefix) {
    size_t n = strlen(prefix);
    return len >= n && memcmp(s, prefix, n) == 0;
}

static size_t call(const kvstore *kv, const char *req, char *out, size_t cap) {
    return http_handle(kv, req, strlen(req), out, cap);
}

static void test_routes(void) {
    kvstore *kv = fixture();
    CHECK(kv != nullptr);
    char out[4096];
    size_t n = call(kv, "GET /up HTTP/1.1\r\nHost: x\r\n\r\n", out, sizeof out);
    CHECK(starts_with(out, n, "HTTP/1.1 200 OK\r\n"));
    CHECK(strstr(out, "\r\n\r\nok\n") != nullptr);

    n = call(kv, "GET /v/greeting HTTP/1.1\r\n\r\n", out, sizeof out);
    CHECK(starts_with(out, n, "HTTP/1.1 200 OK\r\n"));
    CHECK(strstr(out, "Content-Length: 6\r\n") != nullptr);

    n = call(kv, "GET /v/nope HTTP/1.1\r\n\r\n", out, sizeof out);
    CHECK(starts_with(out, n, "HTTP/1.1 404"));
    n = call(kv, "POST /up HTTP/1.1\r\n\r\n", out, sizeof out);
    CHECK(starts_with(out, n, "HTTP/1.1 405"));
    n = call(kv, "garbage", out, sizeof out);
    CHECK(starts_with(out, n, "HTTP/1.1 400"));
    kvstore_destroy(kv);
}

static void test_small_buffer_is_refused_not_truncated(void) {
    kvstore *kv = fixture();
    char out[16];
    CHECK_EQ_INT(call(kv, "GET /up HTTP/1.1\r\n\r\n", out, sizeof out), 0);
    kvstore_destroy(kv);
}

int main(void) {
    RUN(test_routes);
    RUN(test_small_buffer_is_refused_not_truncated);
    return TEST_EXIT();
}
