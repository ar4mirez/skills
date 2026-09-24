/* Config parser for confd. */
#include <stddef.h>

struct item {
    char key[32];
    char value[128];
};

struct config {
    struct item *items;
    size_t count;
    size_t cap;
};

struct config *config_load();
char *config_get(struct config *cfg, const char *key);
char *config_describe(struct config *cfg);
void config_free(struct config *cfg);
