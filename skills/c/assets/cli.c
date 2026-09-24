/* kvstore-cli: print the value for KEY from a key=value FILE.
 * Exit codes: 0 found, 1 not found, 2 usage or input error. */
#include "kvstore/kvstore.h"

#include <errno.h>
#include <stdckdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static constexpr size_t MAX_INPUT = 1u << 20; /* refuse inputs over 1 MiB */

static void usage(FILE *to) {
    fputs("usage: kvstore-cli FILE KEY\n"
          "Print the value of KEY from FILE (key=value lines; '-' reads stdin).\n"
          "Exit codes: 0 found, 1 not found, 2 usage or input error.\n",
          to);
}

/* Reads the whole stream into a malloc'd buffer the caller frees. */
static char *read_all(FILE *in, size_t *out_len) {
    size_t cap = 4096;
    size_t len = 0;
    char *buf = malloc(cap);
    if (!buf) {
        return nullptr;
    }
    for (;;) {
        if (len == cap) {
            if (cap >= MAX_INPUT) {
                free(buf);
                errno = EFBIG;
                return nullptr;
            }
            size_t new_cap = 0;
            if (ckd_mul(&new_cap, cap, (size_t)2)) {
                free(buf);
                errno = EFBIG;
                return nullptr;
            }
            char *bigger = realloc(buf, new_cap); /* never p = realloc(p, ...) */
            if (!bigger) {
                free(buf);
                return nullptr;
            }
            buf = bigger;
            cap = new_cap;
        }
        size_t want = cap - len;
        size_t n = fread(buf + len, 1, want, in);
        len += n;
        if (n < want) { /* short read: EOF or error, never read again */
            if (ferror(in)) {
                free(buf);
                return nullptr;
            }
            break;
        }
    }
    *out_len = len;
    return buf;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--help") == 0) {
        usage(stdout);
        return 0;
    }
    if (argc != 3) {
        usage(stderr);
        return 2;
    }
    const char *path = argv[1];
    const char *key = argv[2];

    size_t len = 0;
    char *text = nullptr;
    int saved = 0;
    if (strcmp(path, "-") == 0) {
        errno = 0;
        text = read_all(stdin, &len);
        saved = errno;
    } else {
        FILE *in = fopen(path, "rb");
        if (!in) {
            fprintf(stderr, "kvstore-cli: %s: %s\n", path, strerror(errno));
            return 2;
        }
        errno = 0;
        text = read_all(in, &len);
        saved = errno;
        fclose(in);
    }
    if (!text) {
        fprintf(stderr, "kvstore-cli: %s: %s\n", path, saved ? strerror(saved) : "read error");
        return 2;
    }

    int rc = 2;
    kvstore *kv = nullptr;
    kvstore_status st = kvstore_create(&kv);
    if (st != KVSTORE_OK) {
        fprintf(stderr, "kvstore-cli: %s\n", kvstore_status_str(st));
        goto out;
    }
    size_t err_line = 0;
    st = kvstore_parse(kv, text, len, &err_line);
    if (st != KVSTORE_OK) {
        fprintf(stderr, "kvstore-cli: %s:%zu: %s\n", path, err_line, kvstore_status_str(st));
        goto out;
    }
    const char *value = nullptr;
    st = kvstore_get(kv, key, &value);
    if (st == KVSTORE_OK) {
        puts(value);
        rc = 0;
    } else if (st == KVSTORE_ERR_NOT_FOUND) {
        rc = 1;
    } else {
        fprintf(stderr, "kvstore-cli: %s: %s\n", key, kvstore_status_str(st));
    }
out: /* single cleanup path: every exit after allocation comes through here */
    kvstore_destroy(kv);
    free(text);
    return rc;
}
