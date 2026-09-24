/* Internal arena (region) allocator: many allocations, one free.
 * Use it for memory that shares a lifetime (a request, a parse, a store).
 * Not thread-safe. Not part of the public API. */
#ifndef KVSTORE_ARENA_H
#define KVSTORE_ARENA_H

#include <stddef.h>

typedef struct arena_block arena_block;

typedef struct arena {
    arena_block *head; /* newest block first */
    size_t block_size; /* default capacity of new blocks */
} arena;

/* A zeroed arena is valid; arena_init only sets the block size. */
void arena_init(arena *a, size_t block_size);

/* Frees every block. The arena can be reused afterwards. */
void arena_release(arena *a);

/* Returns size bytes aligned to max_align_t, or nullptr on overflow/OOM.
 * The memory is owned by the arena. */
[[nodiscard]] void *arena_alloc(arena *a, size_t size);

/* Copies len bytes of s and appends a NUL. Owned by the arena. */
[[nodiscard]] char *arena_strndup(arena *a, const char *s, size_t len);

#endif /* KVSTORE_ARENA_H */
