/* C ABI for the tally library (src/c_api.zig). Link zig-out/lib/libtally.a. */
#ifndef TALLY_H
#define TALLY_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum { TALLY_OK = 0, TALLY_OUT_OF_MEMORY = 1, TALLY_WORD_TOO_LONG = 2 } tally_status;

/* Counts whitespace-separated words in text[0..len). Does not retain `text`. */
tally_status tally_count(const char *text, size_t len, uint64_t *out_total, size_t *out_distinct);

#ifdef __cplusplus
}
#endif

#endif
