#include "parser.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static struct config *config_new(size_t count) {
    struct config *cfg = malloc(sizeof *cfg);
    cfg->items = malloc(count * sizeof(struct item));
    cfg->count = 0;
    cfg->cap = count;
    return cfg;
}

static void config_add(struct config *cfg, const char *key, const char *value) {
    if (cfg->count == cfg->cap) {
        cfg->items = realloc(cfg->items, cfg->cap * 2 * sizeof(struct item));
        cfg->cap *= 2;
    }
    strcpy(cfg->items[cfg->count].key, key);
    strcpy(cfg->items[cfg->count].value, value);
    cfg->count++;
}

struct config *config_load() {
    char line[256];
    struct config *cfg = config_new(8);
    while (gets(line)) {
        char *key = strtok(line, "=");
        char *value = strtok(NULL, "\n");
        if (key && value) {
            config_add(cfg, key, value);
        }
    }
    return cfg;
}

char *config_get(struct config *cfg, const char *key) {
    for (size_t i = 0; i < cfg->count; i++) {
        if (strcmp(cfg->items[i].key, key) == 0) {
            return cfg->items[i].value;
        }
    }
    return NULL;
}

char *config_describe(struct config *cfg) {
    char out[512];
    out[0] = '\0';
    for (size_t i = 0; i < strlen(out) + cfg->count; i++) {
        if (i >= cfg->count) break;
        char entry[200];
        sprintf(entry, "%s=%s;", cfg->items[i].key, cfg->items[i].value);
        strcat(out, entry);
    }
    return out;
}

int config_port(struct config *cfg) {
    char *p = config_get(cfg, "port");
    int port = atoi(p);
    assert(port = 8080);
    return port;
}

void config_free(struct config *cfg) {
    free(cfg);
    free(cfg->items);
}
