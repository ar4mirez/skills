#include "arena.h"

#include <stdckdint.h>
#include <stdlib.h>
#include <string.h>

struct arena_block {
    arena_block *next;
    size_t used;
    size_t cap;
    alignas(max_align_t) unsigned char data[];
};

static constexpr size_t ALIGN = alignof(max_align_t);
static constexpr size_t DEFAULT_BLOCK = 4096;

void arena_init(arena *a, size_t block_size) {
    a->head = nullptr;
    a->block_size = block_size ? block_size : DEFAULT_BLOCK;
}

void arena_release(arena *a) {
    arena_block *b = a->head;
    while (b) {
        arena_block *next = b->next;
        free(b);
        b = next;
    }
    a->head = nullptr;
}

static arena_block *block_new(size_t cap) {
    size_t total = 0;
    if (ckd_add(&total, sizeof(arena_block), cap)) {
        return nullptr;
    }
    arena_block *b = malloc(total);
    if (!b) {
        return nullptr;
    }
    b->next = nullptr;
    b->used = 0;
    b->cap = cap;
    return b;
}

void *arena_alloc(arena *a, size_t size) {
    size_t rounded = 0;
    if (ckd_add(&rounded, size, ALIGN - 1)) {
        return nullptr;
    }
    rounded &= ~(ALIGN - 1);
    if (rounded == 0) {
        rounded = ALIGN;
    }

    arena_block *b = a->head;
    if (!b || b->cap - b->used < rounded) {
        size_t base = a->block_size ? a->block_size : DEFAULT_BLOCK;
        size_t cap = rounded > base ? rounded : base;
        b = block_new(cap);
        if (!b) {
            return nullptr;
        }
        b->next = a->head;
        a->head = b;
    }
    void *p = b->data + b->used;
    b->used += rounded;
    return p;
}

char *arena_strndup(arena *a, const char *s, size_t len) {
    size_t n = 0;
    if (ckd_add(&n, len, 1)) {
        return nullptr;
    }
    char *p = arena_alloc(a, n);
    if (!p) {
        return nullptr;
    }
    memcpy(p, s, len);
    p[len] = '\0';
    return p;
}
