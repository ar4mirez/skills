/* libFuzzer target for kvstore_parse, plus lookups on whatever it stored.
 * Build with -DKVSTORE_FUZZ=ON using LLVM clang; Apple clang ships no
 * libFuzzer runtime, so there the same file builds with KVSTORE_FUZZ_REPLAY,
 * a tiny main() that replays corpus files (handy as a CTest regression). */
#include "kvstore/kvstore.h"

#include <stddef.h>
#include <stdint.h>

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size);

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    kvstore *kv = nullptr;
    if (kvstore_create(&kv) != KVSTORE_OK) {
        return 0;
    }
    size_t line = 0;
    (void)kvstore_parse(kv, (const char *)data, size, &line);
    const char *value = nullptr;
    (void)kvstore_get(kv, "a", &value);
    kvstore_destroy(kv);
    return 0; /* values other than 0 and -1 are reserved */
}

#ifdef KVSTORE_FUZZ_REPLAY
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    static uint8_t buf[1u << 16];
    for (int i = 1; i < argc; i++) {
        FILE *f = fopen(argv[i], "rb");
        if (!f) {
            perror(argv[i]);
            return 2;
        }
        size_t n = fread(buf, 1, sizeof buf, f);
        fclose(f);
        LLVMFuzzerTestOneInput(buf, n);
    }
    return 0;
}
#endif
