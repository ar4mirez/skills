#include "kvstore/kvstore.h"

#include "arena.h"

#include <stdckdint.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* Open addressing with linear probing. Strings live in the arena, so destroy
 * is one arena_release() plus the slot array. Replaced values stay in the
 * arena until destroy: fine for config-sized data, and it keeps borrowed
 * pointers from kvstore_get() from dangling on unrelated writes. */
typedef struct slot {
    const char *key; /* nullptr = empty */
    const char *value;
    uint64_t hash;
} slot;

struct kvstore {
    arena strings;
    slot *slots;
    size_t cap; /* power of two */
    size_t count;
};

static constexpr size_t INITIAL_CAP = 16;

static uint64_t fnv1a(const char *s, size_t len) {
    uint64_t h = 14695981039346656037u;
    for (size_t i = 0; i < len; i++) {
        h ^= (unsigned char)s[i];
        h *= 1099511628211u;
    }
    return h;
}

static bool key_char_ok(char c) {
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' ||
           c == '.' || c == '-';
}

static bool key_ok(const char *key, size_t len) {
    if (len == 0 || len > KVSTORE_MAX_KEY) {
        return false;
    }
    for (size_t i = 0; i < len; i++) {
        if (!key_char_ok(key[i])) {
            return false;
        }
    }
    return true;
}

kvstore_status kvstore_create(kvstore **out) {
    if (!out) {
        return KVSTORE_ERR_INVALID;
    }
    kvstore *kv = calloc(1, sizeof *kv);
    if (!kv) {
        return KVSTORE_ERR_NOMEM;
    }
    kv->slots = calloc(INITIAL_CAP, sizeof *kv->slots);
    if (!kv->slots) {
        free(kv);
        return KVSTORE_ERR_NOMEM;
    }
    kv->cap = INITIAL_CAP;
    arena_init(&kv->strings, 0);
    *out = kv;
    return KVSTORE_OK;
}

void kvstore_destroy(kvstore *kv) {
    if (!kv) {
        return;
    }
    arena_release(&kv->strings);
    free(kv->slots);
    free(kv);
}

static slot *find_slot(slot *slots, size_t cap, const char *key, size_t len, uint64_t hash) {
    size_t mask = cap - 1;
    for (size_t i = (size_t)hash & mask;; i = (i + 1) & mask) {
        slot *s = &slots[i];
        if (!s->key || (s->hash == hash && strncmp(s->key, key, len) == 0 && s->key[len] == '\0')) {
            return s;
        }
    }
}

static kvstore_status grow(kvstore *kv) {
    size_t new_cap = 0;
    if (ckd_mul(&new_cap, kv->cap, (size_t)2)) {
        return KVSTORE_ERR_NOMEM;
    }
    slot *fresh = calloc(new_cap, sizeof *fresh); /* calloc checks n * size overflow */
    if (!fresh) {
        return KVSTORE_ERR_NOMEM;
    }
    for (size_t i = 0; i < kv->cap; i++) {
        const slot *old = &kv->slots[i];
        if (old->key) {
            *find_slot(fresh, new_cap, old->key, strlen(old->key), old->hash) = *old;
        }
    }
    free(kv->slots);
    kv->slots = fresh;
    kv->cap = new_cap;
    return KVSTORE_OK;
}

static kvstore_status set_n(kvstore *kv, const char *key, size_t klen, const char *value,
                            size_t vlen) {
    if (!key_ok(key, klen) || vlen > KVSTORE_MAX_VALUE) {
        return KVSTORE_ERR_INVALID;
    }
    /* Keep the load factor under 3/4 so probes stay short and always end. */
    if ((kv->count + 1) * 4 > kv->cap * 3) {
        kvstore_status st = grow(kv);
        if (st != KVSTORE_OK) {
            return st;
        }
    }
    uint64_t hash = fnv1a(key, klen);
    slot *s = find_slot(kv->slots, kv->cap, key, klen, hash);
    char *v = arena_strndup(&kv->strings, value, vlen);
    if (!v) {
        return KVSTORE_ERR_NOMEM;
    }
    if (!s->key) {
        char *k = arena_strndup(&kv->strings, key, klen);
        if (!k) {
            return KVSTORE_ERR_NOMEM;
        }
        s->key = k;
        s->hash = hash;
        kv->count++;
    }
    s->value = v;
    return KVSTORE_OK;
}

kvstore_status kvstore_set(kvstore *kv, const char *key, const char *value) {
    if (!kv || !key || !value) {
        return KVSTORE_ERR_INVALID;
    }
    return set_n(kv, key, strlen(key), value, strlen(value));
}

kvstore_status kvstore_get(const kvstore *kv, const char *key, const char **out_value) {
    if (!kv || !key || !out_value) {
        return KVSTORE_ERR_INVALID;
    }
    size_t len = strlen(key);
    if (!key_ok(key, len)) {
        return KVSTORE_ERR_INVALID;
    }
    const slot *s = find_slot(kv->slots, kv->cap, key, len, fnv1a(key, len));
    if (!s->key) {
        return KVSTORE_ERR_NOT_FOUND;
    }
    *out_value = s->value;
    return KVSTORE_OK;
}

size_t kvstore_count(const kvstore *kv) {
    return kv ? kv->count : 0;
}

static bool is_space(char c) {
    return c == ' ' || c == '\t' || c == '\r';
}

static void trim(const char **s, size_t *len) {
    while (*len > 0 && is_space(**s)) {
        (*s)++;
        (*len)--;
    }
    while (*len > 0 && is_space((*s)[*len - 1])) {
        (*len)--;
    }
}

kvstore_status kvstore_parse(kvstore *kv, const char *text, size_t len, size_t *err_line) {
    if (!kv || (!text && len > 0)) {
        return KVSTORE_ERR_INVALID;
    }
    size_t line_no = 0;
    size_t pos = 0;
    while (pos < len) {
        line_no++;
        const char *line = text + pos;
        const char *nl = memchr(line, '\n', len - pos);
        size_t line_len = nl ? (size_t)(nl - line) : len - pos;
        pos += line_len + (nl ? 1 : 0);

        trim(&line, &line_len);
        if (line_len == 0 || line[0] == '#') {
            continue;
        }
        const char *eq = memchr(line, '=', line_len);
        if (!eq || memchr(line, '\0', line_len)) {
            if (err_line) {
                *err_line = line_no;
            }
            return KVSTORE_ERR_SYNTAX;
        }
        const char *key = line;
        size_t klen = (size_t)(eq - line);
        const char *val = eq + 1;
        size_t vlen = line_len - klen - 1;
        trim(&key, &klen);
        trim(&val, &vlen);

        kvstore_status st = set_n(kv, key, klen, val, vlen);
        if (st == KVSTORE_ERR_INVALID) {
            st = KVSTORE_ERR_SYNTAX;
        }
        if (st != KVSTORE_OK) {
            if (err_line) {
                *err_line = line_no;
            }
            return st;
        }
    }
    return KVSTORE_OK;
}

const char *kvstore_status_str(kvstore_status status) {
    switch (status) {
    case KVSTORE_OK:
        return "ok";
    case KVSTORE_ERR_NOMEM:
        return "out of memory";
    case KVSTORE_ERR_INVALID:
        return "invalid argument";
    case KVSTORE_ERR_NOT_FOUND:
        return "not found";
    case KVSTORE_ERR_SYNTAX:
        return "syntax error";
    }
    return "unknown status";
}
