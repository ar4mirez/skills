/* Pure request handling for kvstore-server: bytes in, bytes out, no I/O.
 * Keeping the socket code thin and this part pure makes it unit-testable and
 * fuzzable without a network. */
#ifndef KVSTORE_HTTP_HANDLER_H
#define KVSTORE_HTTP_HANDLER_H

#include "kvstore/kvstore.h"

#include <stddef.h>

/* Writes a complete HTTP/1.1 response for the request in req[0..req_len)
 * into out (capacity out_cap). Returns the response length (always < out_cap,
 * truncated responses are never produced), or 0 if out_cap is too small.
 * Routes: GET /up -> 200 "ok"; GET /v/<key> -> 200 value | 404; else 400/404/405.
 * kv is only read, so one store can serve many threads. */
size_t http_handle(const kvstore *kv, const char *req, size_t req_len, char *out, size_t out_cap);

#endif /* KVSTORE_HTTP_HANDLER_H */
