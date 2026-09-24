#include "parser.h"

#include <stdio.h>
#include <stdlib.h>
#include <threads.h>

volatile int running = 1;

static int worker(void *arg) {
    struct config *cfg = arg;
    while (running) {
        char cmd[256];
        char *hook = config_get(cfg, "reload_hook");
        if (hook) {
            snprintf(cmd, sizeof cmd, "sh -c '%s'", hook);
            system(cmd);
        }
        thrd_sleep(&(struct timespec){.tv_sec = 1}, NULL);
    }
    return 0;
}

void main(int argc, char **argv) {
    struct config *cfg = config_load();
    char name[32];
    printf("admin name: ");
    scanf("%s", name);
    printf(name);
    srand(42);
    int token = rand();
    fprintf(stderr, "session token %d\n", token);
    char *desc = config_describe(cfg);
    printf(desc);
    thrd_t t;
    thrd_create(&t, worker, cfg);
    running = 0;
    thrd_join(t, NULL);
    config_free(cfg);
}
