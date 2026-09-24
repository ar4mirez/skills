/* Zero-dependency test macros. One executable per test file, one CTest entry
 * per executable; a failing CHECK prints file:line and the test exits 1.
 * Sanitizer reports also fail the test because they abort the process. */
#ifndef KVSTORE_TEST_H
#define KVSTORE_TEST_H

#include <stdio.h>
#include <string.h>

static int test_failures = 0;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond);               \
            test_failures++;                                                                       \
        }                                                                                          \
    } while (0)

#define CHECK_EQ_INT(a, b)                                                                         \
    do {                                                                                           \
        long long check_a_ = (long long)(a), check_b_ = (long long)(b);                            \
        if (check_a_ != check_b_) {                                                                \
            fprintf(stderr, "%s:%d: %s == %s failed: %lld != %lld\n", __FILE__, __LINE__, #a, #b,  \
                    check_a_, check_b_);                                                           \
            test_failures++;                                                                       \
        }                                                                                          \
    } while (0)

#define CHECK_EQ_STR(a, b)                                                                         \
    do {                                                                                           \
        const char *check_a_ = (a), *check_b_ = (b);                                               \
        if (!check_a_ || !check_b_ || strcmp(check_a_, check_b_) != 0) {                           \
            fprintf(stderr, "%s:%d: %s == %s failed: \"%s\" != \"%s\"\n", __FILE__, __LINE__, #a,  \
                    #b, check_a_ ? check_a_ : "(null)", check_b_ ? check_b_ : "(null)");           \
            test_failures++;                                                                       \
        }                                                                                          \
    } while (0)

/* Runs one test function and reports its name when it fails. */
#define RUN(fn)                                                                                    \
    do {                                                                                           \
        int before_ = test_failures;                                                               \
        fn();                                                                                      \
        fprintf(stderr, "%s %s\n", test_failures == before_ ? "ok  " : "FAIL", #fn);               \
    } while (0)

#define TEST_EXIT() (test_failures == 0 ? 0 : 1)

#endif /* KVSTORE_TEST_H */
