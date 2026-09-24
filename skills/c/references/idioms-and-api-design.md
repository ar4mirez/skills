# Idioms and API design

## Contents
- Naming and files
- API shape: opaque types, init/destroy, status plus out-params
- Ownership: write it down
- Error handling and errno
- Resource cleanup: one exit path
- Memory: allocation rules and arenas
- Strings and buffers
- Integers
- Macros, const, static
- The "don't" list

## Naming and files

- Use `snake_case` for everything. Prefix every public symbol with the
  library name (`kvstore_get`, `KVSTORE_OK`, `kvstore_status`). C has one
  global namespace, and unprefixed `init()` or `parse()` will collide.
- Macros and enum constants are `UPPER_SNAKE`. Types are unsuffixed
  `snake_case`: `typedef struct kvstore kvstore;`. `_t` is reserved by POSIX.
- Make every function and file-scope variable that isn't in a header
  `static`. Internal linkage is C's module system, and it lets the compiler
  inline and warn about unused code.
- Use one header per module, with an include guard
  (`#ifndef NAME_MODULE_H`) or `#pragma once`. Include guards are standard
  C; `#pragma once` is universally supported. Pick one per project. The
  templates use guards.
- Include order: the module's own header first (proves it's
  self-contained), then project headers, then system headers.

## API shape

```c
typedef struct kvstore kvstore;                      /* opaque: layout is private */
typedef enum kvstore_status { KVSTORE_OK = 0, KVSTORE_ERR_NOMEM, ... } kvstore_status;

KVSTORE_NODISCARD kvstore_status kvstore_create(kvstore **out);   /* caller owns *out */
void kvstore_destroy(kvstore *kv);                                  /* NULL-safe */
KVSTORE_NODISCARD kvstore_status kvstore_get(const kvstore *kv, const char *key,
                                             const char **out_value); /* borrowed */
```

- **Opaque structs** (declared in the header, defined in the `.c` file). You
  can change fields without breaking the ABI, callers can't bypass
  invariants, and `sizeof` misuse becomes impossible. Expose a struct only
  when callers must stack-allocate it for performance, and then add an
  `_init`/`_release` pair that takes a pointer.
- **Every function that can fail returns a status enum.** Results go through
  out-parameters, which are written **only on success**. Callers can then
  pass uninitialized outputs and trust them afterwards. Zero is success.
  Return a status even when there's one failure mode today, because there'll
  be two tomorrow.
- **`[[nodiscard]]` on every status and on every owning pointer** (through a
  macro in public headers, since they stay C11-compatible). An ignored status
  is the most common C bug that reviews miss.
- **Paired lifecycle functions:** `create`/`destroy` for heap objects, and
  `init`/`release` for caller-provided storage. Destroy is NULL-safe, like
  `free`, so cleanup paths don't need conditionals.
- **`const` on every pointer the function doesn't write through.** Read-only
  accessors take `const kvstore *`. That documents thread safety (see
  `concurrency-and-performance.md`) and lets the compiler catch mistakes.
- **Take lengths, not just NUL-terminated strings, for untrusted bytes:**
  `kvstore_parse(kv, text, len, &err_line)`. Network input isn't
  NUL-terminated, and fuzzers feed you arbitrary bytes.
- **Report where parsing failed** (`err_line`) through an optional
  out-parameter.
- Provide a `*_status_str()` that returns a static string, so every caller
  prints errors the same way.

## Ownership: write it down

State ownership in the header on every pointer that crosses the API,
using the same words everywhere:
- **"The caller owns it; release it with X"**: the function allocated it.
- **"Borrowed; valid until Y"**: the pointer stays owned by the callee.
  Name the event that invalidates it (the next `set` of that key, or
  `destroy`).
- **"Copies"**: the callee copies the argument, so the caller may free it
  immediately.

If you can't write the sentence, the design is unclear. Fix the design, not
the comment.

## Error handling and errno

- Library functions return statuses; **they don't print**. Only `main` (or
  the service's request loop) decides what to log.
- **errno is for talking to libc.** Read it immediately after the failing
  call and before any other libc call, because `fprintf` may overwrite it.
  Save it (`int saved = errno;`) if you need it later. Don't use errno as
  your own library's error channel.
- **`strtol` and friends report overflow only through errno.** The correct
  pattern is: set `errno = 0`, call, then check `errno`, check
  `end != s && *end == '\0'`, and range-check the result (`env_long()` in
  `assets/server.c`). `atoi` can't report errors at all and is UB on
  overflow. The audit flags both.
- Check **every** return value from I/O: `fopen`, `fread` (short reads mean
  EOF *or* an error, so check `ferror`), `fclose` on written files (it
  flushes; ignoring it loses data), `snprintf` (see below), `pthread_create`.
- `assert` is for programmer errors (violated preconditions inside the
  library). It's never for input validation, and it must never have side
  effects: CMake's Release flags include `-DNDEBUG`, which deletes the whole
  expression.

## Resource cleanup: one exit path

Once a function owns more than one resource, use a single cleanup label:

```c
int rc = 2;
kvstore *kv = nullptr;
char *text = read_all(in, &len);
if (!text) goto out;
if (kvstore_create(&kv) != KVSTORE_OK) goto out;
...
rc = 0;
out:
    kvstore_destroy(kv);   /* NULL-safe destroy makes the label unconditional */
    free(text);
    return rc;
```

Initialize every resource to `nullptr` or `-1` *before* the first `goto`.
Release resources in reverse order. This is idiomatic C, used by the Linux
kernel and CPython, and it beats nested `if` pyramids or early returns that
each duplicate cleanup. Don't adopt `defer` or `__attribute__((cleanup))` in
portable code yet.

## Memory

- **Check every allocation immediately** and return `..._ERR_NOMEM`. Linux
  overcommit doesn't make `malloc` failure impossible: containers with memory
  limits, `ulimit -v`, 32-bit targets, and huge requests all return NULL.
- **Never write `p = realloc(p, n)`.** On failure it returns NULL and leaks
  the original block. Assign to a temporary, check it, then replace.
- **Size arithmetic is checked.** Use `calloc(n, size)` (it checks the
  multiplication) or `ckd_mul(&bytes, n, size)` before `malloc`/`realloc`.
  `malloc(n * sizeof *p)` with an attacker-influenced `n` is a classic
  heap overflow.
- Write `sizeof *p`, not `sizeof(struct foo)`, so the size follows the
  variable's type.
- `free(NULL)` is fine. After `free`, either the object is gone (the struct
  itself was freed) or set the field to `nullptr` if the struct lives on.
- **Arena allocators for request-scoped or object-scoped memory.** When many
  allocations share one lifetime (a request, a parse, a store's strings),
  allocate them from an arena and free the arena once
  (`assets/arena.{h,c}`). You get no per-object frees, no leaks on error
  paths, and fast bump allocation. The tradeoff is that memory for replaced
  values isn't reclaimed until the arena is released. Document that, as
  `kvstore.c` does.
- Stack buffers are fine up to a few KiB. Never use VLAs or `alloca` for
  sizes that come from input (`-Wvla` is on). Stack exhaustion can't be
  caught.

## Strings and buffers

- Build strings with `snprintf(buf, sizeof buf, ...)` and **check its
  return value**: `n < 0` is an encoding error, and `(size_t)n >= sizeof buf`
  means it was truncated. Decide explicitly whether truncation is an error.
  In `http_handler.c` it is: the handler returns 0 instead of sending a
  truncated response.
- Copy known-length data with `memcpy` plus an explicit terminator, after
  checking the length against the destination size.
- **Banned:** `gets` (removed in C11), `strcpy`, `strcat`, `sprintf`,
  `vsprintf`, and `scanf("%s")` without a width. **Discouraged:** `strncpy`
  (it doesn't terminate on truncation, and it zero-pads) and `strtok` (hidden
  global state).
- Never pass external data as a format string: `printf(user)` is a
  format-string vulnerability. Write `printf("%s", user)`.
  `-Wformat=2 -Werror=format-security` catches many cases, and the audit
  catches the rest.
- Don't put `strlen` in a loop condition. Compute the length once.

## Integers

- Use `size_t` for sizes, counts, and indexes. Use fixed-width types
  (`uint32_t`) for wire formats and hashes.
- `-Wconversion -Wsign-conversion` are on. Fix each warning with an explicit
  cast *after* a range check, never with a bare cast to silence it.
- Signed overflow is UB. Use `ckd_add`/`ckd_mul` for input-derived math, and
  unsigned types for hashes that wrap on purpose (the FNV-1a in
  `kvstore.c`).
- Compare signed and unsigned values only after checking the signed one is
  non-negative.

## Macros, const, static

- Prefer `static constexpr` (C23) or `enum` constants to `#define` for
  numbers, because they have a type and a scope. Prefer `static inline`
  functions to function-like macros.
- When a macro is unavoidable (for example the test macros), wrap statements
  in `do { ... } while (0)`, parenthesize parameters, and evaluate each
  parameter once (copy it into a local).
- Mark file-scope lookup tables `static const` so they go in read-only
  memory.

## The "don't" list

- Don't return a pointer to a local array. Return an owned buffer or take
  `(char *out, size_t cap)`.
- Don't free and then read (`free(cfg); free(cfg->items);`). Release in
  reverse order of acquisition.
- Don't use `volatile` for thread communication. Use `<stdatomic.h>`.
  `volatile sig_atomic_t` is only for signal handlers.
- Don't call non-async-signal-safe functions (`printf`, `malloc`, locks) in
  signal handlers. Block the signals and `sigwait()` in one thread instead.
- Don't use `rand()` for anything security-related. Use `getrandom()`
  (Linux) or `arc4random_buf()` (BSD/macOS, glibc ≥ 2.36).
- Don't write `void main`, or `int main()` in a header-exposed prototype
  (pre-C23 that's unprototyped).
- Don't `#include` a `.c` file. Don't put definitions (non-`static inline`)
  in headers.
- Don't cast `malloc`'s result in C (it hides a missing `<stdlib.h>` in old
  code). Don't use `sizeof(type)` when `sizeof *p` works.
- Don't hide pointers behind typedefs (`typedef struct x *x_handle;`).
  Ownership and `const` become invisible.
