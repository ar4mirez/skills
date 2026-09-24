#include "http_handler.h"

#include <stdio.h>
#include <string.h>

static size_t respond(char *out, size_t cap, int code, const char *reason, const char *body) {
    int n = snprintf(out, cap,
                     "HTTP/1.1 %d %s\r\n"
                     "Content-Type: text/plain; charset=utf-8\r\n"
                     "Content-Length: %zu\r\n"
                     "Connection: close\r\n"
                     "\r\n"
                     "%s",
                     code, reason, strlen(body), body);
    /* snprintf returns the would-be length: check it, never assume it fit. */
    if (n < 0 || (size_t)n >= cap) {
        return 0;
    }
    return (size_t)n;
}

size_t http_handle(const kvstore *kv, const char *req, size_t req_len, char *out, size_t out_cap) {
    const char *line_end = memchr(req, '\r', req_len);
    if (!line_end) {
        return respond(out, out_cap, 400, "Bad Request", "bad request\n");
    }
    size_t line_len = (size_t)(line_end - req);

    static const char get[] = "GET ";
    if (line_len < sizeof get - 1 || memcmp(req, get, sizeof get - 1) != 0) {
        return respond(out, out_cap, 405, "Method Not Allowed", "method not allowed\n");
    }
    const char *path = req + (sizeof get - 1);
    const char *path_end = memchr(path, ' ', (size_t)(line_end - path));
    if (!path_end) {
        return respond(out, out_cap, 400, "Bad Request", "bad request\n");
    }
    size_t path_len = (size_t)(path_end - path);

    if (path_len == 3 && memcmp(path, "/up", 3) == 0) {
        return respond(out, out_cap, 200, "OK", "ok\n");
    }
    static const char prefix[] = "/v/";
    if (path_len > sizeof prefix - 1 && memcmp(path, prefix, sizeof prefix - 1) == 0) {
        char key[KVSTORE_MAX_KEY + 1];
        size_t klen = path_len - (sizeof prefix - 1);
        if (klen > KVSTORE_MAX_KEY) {
            return respond(out, out_cap, 404, "Not Found", "not found\n");
        }
        memcpy(key, path + sizeof prefix - 1, klen);
        key[klen] = '\0';

        const char *value = nullptr;
        if (kvstore_get(kv, key, &value) == KVSTORE_OK) {
            char body[KVSTORE_MAX_VALUE + 2];
            int n = snprintf(body, sizeof body, "%s\n", value);
            if (n < 0 || (size_t)n >= sizeof body) {
                return respond(out, out_cap, 500, "Internal Server Error", "error\n");
            }
            return respond(out, out_cap, 200, "OK", body);
        }
    }
    return respond(out, out_cap, 404, "Not Found", "not found\n");
}
