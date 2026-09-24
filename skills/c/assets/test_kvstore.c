#include "kvstore/kvstore.h"
#include "test.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>

static void test_set_get_replace(void) {
    kvstore *kv = nullptr;
    CHECK_EQ_INT(kvstore_create(&kv), KVSTORE_OK);
    CHECK_EQ_INT(kvstore_set(kv, "name", "alpha"), KVSTORE_OK);
    CHECK_EQ_INT(kvstore_set(kv, "name", "beta"), KVSTORE_OK);
    const char *v = nullptr;
    CHECK_EQ_INT(kvstore_get(kv, "name", &v), KVSTORE_OK);
    CHECK_EQ_STR(v, "beta");
    CHECK_EQ_INT(kvstore_count(kv), 1);
    CHECK_EQ_INT(kvstore_get(kv, "missing", &v), KVSTORE_ERR_NOT_FOUND);
    kvstore_destroy(kv);
}

static void test_rejects_bad_input(void) {
    kvstore *kv = nullptr;
    CHECK_EQ_INT(kvstore_create(nullptr), KVSTORE_ERR_INVALID);
    CHECK_EQ_INT(kvstore_create(&kv), KVSTORE_OK);
    CHECK_EQ_INT(kvstore_set(kv, "", "x"), KVSTORE_ERR_INVALID);
    CHECK_EQ_INT(kvstore_set(kv, "has space", "x"), KVSTORE_ERR_INVALID);
    CHECK_EQ_INT(kvstore_set(kv, nullptr, "x"), KVSTORE_ERR_INVALID);
    char long_key[KVSTORE_MAX_KEY + 2];
    memset(long_key, 'k', sizeof long_key - 1);
    long_key[sizeof long_key - 1] = '\0';
    CHECK_EQ_INT(kvstore_set(kv, long_key, "x"), KVSTORE_ERR_INVALID);
    kvstore_destroy(kv);
    kvstore_destroy(nullptr); /* documented no-op */
}

static void test_grows_past_initial_capacity(void) {
    kvstore *kv = nullptr;
    CHECK_EQ_INT(kvstore_create(&kv), KVSTORE_OK);
    char key[32];
    char val[32];
    for (int i = 0; i < 1000; i++) {
        snprintf(key, sizeof key, "k%d", i);
        snprintf(val, sizeof val, "v%d", i);
        CHECK_EQ_INT(kvstore_set(kv, key, val), KVSTORE_OK);
    }
    CHECK_EQ_INT(kvstore_count(kv), 1000);
    const char *v = nullptr;
    CHECK_EQ_INT(kvstore_get(kv, "k777", &v), KVSTORE_OK);
    CHECK_EQ_STR(v, "v777");
    kvstore_destroy(kv);
}

static void test_parse(void) {
    static const char text[] = "# comment\n"
                               "\n"
                               "  host = example.com  \n"
                               "port=8080\r\n"
                               "empty=\n"
                               "last=no-newline";
    kvstore *kv = nullptr;
    CHECK_EQ_INT(kvstore_create(&kv), KVSTORE_OK);
    size_t line = 0;
    CHECK_EQ_INT(kvstore_parse(kv, text, sizeof text - 1, &line), KVSTORE_OK);
    const char *v = nullptr;
    CHECK_EQ_INT(kvstore_get(kv, "host", &v), KVSTORE_OK);
    CHECK_EQ_STR(v, "example.com");
    CHECK_EQ_INT(kvstore_get(kv, "port", &v), KVSTORE_OK);
    CHECK_EQ_STR(v, "8080");
    CHECK_EQ_INT(kvstore_get(kv, "empty", &v), KVSTORE_OK);
    CHECK_EQ_STR(v, "");
    CHECK_EQ_INT(kvstore_get(kv, "last", &v), KVSTORE_OK);
    CHECK_EQ_STR(v, "no-newline");
    kvstore_destroy(kv);
}

static void test_parse_reports_line(void) {
    static const char text[] = "a=1\nb=2\nno equals sign\n";
    kvstore *kv = nullptr;
    CHECK_EQ_INT(kvstore_create(&kv), KVSTORE_OK);
    size_t line = 0;
    CHECK_EQ_INT(kvstore_parse(kv, text, sizeof text - 1, &line), KVSTORE_ERR_SYNTAX);
    CHECK_EQ_INT(line, 3);
    CHECK_EQ_INT(kvstore_count(kv), 2);
    kvstore_destroy(kv);
}

static void test_status_str(void) {
    CHECK_EQ_STR(kvstore_status_str(KVSTORE_OK), "ok");
    /* NOLINTNEXTLINE(clang-analyzer-optin.core.EnumCastOutOfRange): deliberate */
    CHECK_EQ_STR(kvstore_status_str((kvstore_status)99), "unknown status");
}

/* Concurrent readers of a fully built store: must be clean under TSan. */
static void *reader(void *arg) {
    const kvstore *kv = arg;
    for (int i = 0; i < 10000; i++) {
        const char *v = nullptr;
        if (kvstore_get(kv, "shared", &v) != KVSTORE_OK || strcmp(v, "yes") != 0) {
            return (void *)1;
        }
    }
    return nullptr;
}

static void test_concurrent_readers(void) {
    kvstore *kv = nullptr;
    CHECK_EQ_INT(kvstore_create(&kv), KVSTORE_OK);
    CHECK_EQ_INT(kvstore_set(kv, "shared", "yes"), KVSTORE_OK);
    pthread_t threads[8];
    for (size_t i = 0; i < 8; i++) {
        CHECK_EQ_INT(pthread_create(&threads[i], nullptr, reader, kv), 0);
    }
    for (size_t i = 0; i < 8; i++) {
        void *res = nullptr;
        pthread_join(threads[i], &res);
        CHECK(res == nullptr);
    }
    kvstore_destroy(kv);
}

int main(void) {
    RUN(test_set_get_replace);
    RUN(test_rejects_bad_input);
    RUN(test_grows_past_initial_capacity);
    RUN(test_parse);
    RUN(test_parse_reports_line);
    RUN(test_status_str);
    RUN(test_concurrent_readers);
    return TEST_EXIT();
}
