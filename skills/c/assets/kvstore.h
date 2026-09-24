/* kvstore: an in-memory key/value store parsed from "key=value" text.
 *
 * Conventions used by every function in this header:
 *   - Functions that can fail return kvstore_status; results come back
 *     through out-parameters, which are written only on KVSTORE_OK.
 *   - Ownership is stated per function. "Borrowed" pointers stay owned by the
 *     store; never free them.
 *   - Strings are NUL-terminated UTF-8 unless a length is passed.
 *   - A kvstore is not synchronized. Concurrent readers are safe once all
 *     writes are done; any writer needs external locking.
 *
 * This public header stays C11-compatible (consumers may not use C23), so
 * attributes go through macros. The implementation is C23.
 */
#ifndef KVSTORE_KVSTORE_H
#define KVSTORE_KVSTORE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(__cplusplus) && __cplusplus >= 201703L
#define KVSTORE_NODISCARD [[nodiscard]]
#elif defined(__STDC_VERSION__) && __STDC_VERSION__ >= 202311L
#define KVSTORE_NODISCARD [[nodiscard]]
#elif defined(__GNUC__) || defined(__clang__)
#define KVSTORE_NODISCARD __attribute__((warn_unused_result))
#else
#define KVSTORE_NODISCARD
#endif

enum {
    KVSTORE_MAX_KEY = 64,     /* bytes, excluding the NUL */
    KVSTORE_MAX_VALUE = 1024, /* bytes, excluding the NUL */
};

typedef enum kvstore_status {
    KVSTORE_OK = 0,
    KVSTORE_ERR_NOMEM,     /* allocation failed; the store is unchanged */
    KVSTORE_ERR_INVALID,   /* bad argument (NULL, empty or oversized key/value) */
    KVSTORE_ERR_NOT_FOUND, /* key not present */
    KVSTORE_ERR_SYNTAX,    /* parse error; see err_line */
} kvstore_status;

/* Opaque: callers can't depend on the layout, so it can change freely. */
typedef struct kvstore kvstore;

/* Creates an empty store in *out. The caller owns it: release it with
 * kvstore_destroy(). */
KVSTORE_NODISCARD kvstore_status kvstore_create(kvstore **out);

/* Frees the store and every string it holds. NULL is a no-op. */
void kvstore_destroy(kvstore *kv);

/* Copies key and value into the store, replacing an existing value.
 * Keys match [A-Za-z0-9_.-]{1,KVSTORE_MAX_KEY}. */
KVSTORE_NODISCARD kvstore_status kvstore_set(kvstore *kv, const char *key, const char *value);

/* Looks up key. On success *out_value is borrowed: it stays valid until the
 * next kvstore_set() of the same key or kvstore_destroy(). */
KVSTORE_NODISCARD kvstore_status kvstore_get(const kvstore *kv, const char *key,
                                             const char **out_value);

/* Number of distinct keys. */
size_t kvstore_count(const kvstore *kv);

/* Parses len bytes of text (need not be NUL-terminated): one "key=value" per
 * line, blank lines and lines starting with '#' ignored, surrounding spaces
 * trimmed. On KVSTORE_ERR_SYNTAX, *err_line (if non-NULL) gets the 1-based
 * line number. Entries before the failing line stay in the store. */
KVSTORE_NODISCARD kvstore_status kvstore_parse(kvstore *kv, const char *text, size_t len,
                                               size_t *err_line);

/* Static, never NULL. */
const char *kvstore_status_str(kvstore_status status);

#ifdef __cplusplus
}
#endif

#endif /* KVSTORE_KVSTORE_H */
