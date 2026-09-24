#include <stdio.h>
#include <string.h>
#include "tally.h"

int main(void) {
    const char *text = "zig and c and zig";
    uint64_t total = 0;
    size_t distinct = 0;
    if (tally_count(text, strlen(text), &total, &distinct) != TALLY_OK) return 1;
    printf("total=%llu distinct=%zu\n", (unsigned long long)total, distinct);
    return (total == 5 && distinct == 3) ? 0 : 1;
}
