# Idioms, API design, and the "don't" list

The C++ Core Guidelines (https://isocpp.github.io/CppCoreGuidelines/CppCoreGuidelines) are
the reference; rule IDs are cited as (C.20), (R.11), etc. This file is the subset agents get
wrong, with the house choice where the guidelines leave room.

## Contents
- Ownership and RAII
- Special members: the Rule of Zero
- Parameters, views, and lifetimes
- Errors: the policy
- Types: enum class, strong types, nodiscard, constexpr
- Generic code: concepts, not SFINAE
- Ranges and algorithms
- Headers, namespaces, and linkage
- The "don't" list

## Ownership and RAII

- **Every resource has exactly one owner object whose destructor releases it** (R.1). Memory
  → `std::unique_ptr` or a container; files → `std::fstream`; locks → `std::scoped_lock`;
  threads → `std::jthread`; C handles → `std::unique_ptr<T, Deleter>`.
- **No naked `new`/`delete`** (R.11). `std::make_unique<T>(…)`, or better a value or a
  container. The only `new` left in modern code is placement new inside a container
  implementation.
- **`unique_ptr` by default; `shared_ptr` only when ownership is genuinely shared and the
  last owner isn't knowable** (R.20, R.21): caches, graph nodes with multiple parents,
  callbacks that outlive their creator. `shared_ptr` costs an atomic refcount on every copy
  and hides lifetime; "I'm not sure who owns it" is a design bug, not a reason.
- **Raw pointers and references are non-owning** (R.3). `T*` means "optional, non-owning";
  `T&` means "required, non-owning". A raw pointer member that's `delete`d somewhere is a
  bug magnet: the compiler-generated copy duplicates it and you get a double free.
- Wrap C APIs once:
  ```cpp
  struct FileCloser { void operator()(std::FILE* f) const noexcept { std::fclose(f); } };
  using File = std::unique_ptr<std::FILE, FileCloser>;
  ```

## Special members: the Rule of Zero

Classes that only hold RAII members declare **no** destructor, copy, or move operations
(C.20). The reference `Counter` and `ThreadPool` both follow it: `ThreadPool` gets correct
shutdown from `std::jthread`'s destructor (request stop + join) and correct
non-copyability from its `std::mutex` member.

- If you must write one special member (a class that *is* a resource handle), write or
  `= delete` all five (C.21) and make moves `noexcept` (C.66), or `std::vector` copies
  instead of moving on growth.
- **Polymorphic base classes:** `public` + `virtual` destructor, or `protected` + non-virtual
  (C.35). Otherwise, deleting through a base pointer is undefined behavior. Also suppress
  copying in polymorphic bases (C.67) to prevent slicing.
- **Members are destroyed in reverse declaration order.** Declare threads that use other
  members **last**, so they're joined first (see `thread_pool.hpp`).

## Parameters, views, and lifetimes

| Parameter intent | Type |
|---|---|
| read a string | `std::string_view` |
| read a contiguous sequence | `std::span<const T>` |
| read a small trivially copyable value | by value |
| read anything else | `const T&` |
| keep a copy (sink) | by value, then `std::move` into the member |
| modify caller's object | `T&` |
| optional non-owning | `T*` |
| transfer ownership | `std::unique_ptr<T>` by value |

**Views never own.** A `string_view`/`span` is only valid while its target lives:
- `std::string_view sv = make_string() + "x";` dangles immediately (a temporary dies at the
  `;`).
- Returning `string_view`/`span` of a local or a by-value parameter dangles.
- Storing a `string_view` member is a lifetime contract; store `std::string` unless you
  profiled the copy.
- `string_view` isn't null-terminated: don't pass `.data()` to C APIs.
- Clang's `-Wdangling` family and `[[clang::lifetimebound]]` catch some of this; ASan's
  `detect_stack_use_after_return` catches more at runtime.

## Errors: the policy

**Recoverable, expected failures return `std::expected<T, Error>`** (parse errors,
validation, "not found", I/O on user-supplied paths). **Exceptions are for the exceptional:**
allocation failure, broken invariants surfacing from the standard library, and failures in
constructors that can't return a value. **Programming errors are assertions or contracts**,
not error values.

Why this split:
- `std::expected` makes the failure path visible in the signature and costs nothing when you
  don't fail; `[[nodiscard]]` stops callers from ignoring it.
- Exceptions stay enabled: the standard library, GoogleTest, and most dependencies throw, and
  `-fno-exceptions` turns those throws into `abort()`. Don't build error handling on them for
  routine failures, because they're invisible in signatures and slow on the throw path.
- **Exactly one catch-all, at the process boundary** (`main`, a thread entry, a request
  handler), which logs and converts to an exit code or a 500. Inside `catch`, use
  non-throwing output (`std::fputs`) so nothing escapes `main` (clang-tidy's
  `bugprone-exception-escape` enforces this).
- Error types are small structs with an `enum class` code plus context (offset, path), and a
  `message()` for humans. Don't use `std::error_code` for new domain errors unless you
  interoperate with an OS API.
- **Validate before mutating:** `Counter::add` tokenizes and validates first, so a failure
  leaves the object unchanged (the strong guarantee), which the test asserts.
- `std::expected<void, E>` for operations with no result; test with `if (!r)` and read
  `r.error()`. Chain with `.and_then`/`.transform`/`.or_else` when it reads better than ifs.

## Types: enum class, strong types, nodiscard, constexpr

- `enum class` with an explicit underlying type (`: std::uint8_t`) for every enumeration
  (Enum.3). Switch over it without a `default:` so `-Wswitch` flags new enumerators.
- Distinct concepts get distinct types (`struct UserId { std::uint64_t v; };`) when mixing
  them up is plausible. Designated initializers (`{.code = …, .offset = …}`) make aggregates
  self-documenting.
- `[[nodiscard]]` on functions whose result must be used: anything returning `expected`,
  handles, or computed values. Don't blanket it on everything (noise).
- `constexpr` for pure helpers and constants; `consteval` only when compile-time evaluation is
  the point. `constexpr` doesn't make code faster by itself.
- `auto` when the type is obvious from the right-hand side or unutterable; spell it out at API
  boundaries.

## Generic code: concepts, not SFINAE

- Constrain templates with standard concepts (`std::invocable<F&>`, `std::ranges::range`)
  or a named concept. Errors become readable, and overloads stop colliding. Never write new
  `enable_if`.
- Prefer a non-template function taking `std::span`/`std::string_view`/`std::function_ref`
  (C++26, not yet portable) over a template when you don't need the performance: it compiles
  faster and keeps implementation out of headers.
- Deducing `this` (`auto get(this auto const& self)`) replaces CRTP and const/non-const
  duplicate overloads.

## Ranges and algorithms

Use an algorithm when it names the intent (`std::ranges::partial_sort`,
`std::ranges::transform`, `std::ranges::to<std::vector>()`); use a plain loop when the
pipeline would be longer than the loop. Views are lazy and can dangle like `string_view`: don't
return a view over a local container. `views::enumerate` isn't in libc++ yet; use
`views::zip(views::iota(0uz), r)` or an index loop.

## Headers, namespaces, and linkage

- `#pragma once`; include what you use; the matching header first in each `.cpp`.
- Never `using namespace` at file scope in a header (SF.7). In a `.cpp`, prefer namespace
  aliases (`namespace wc = acme::wordcount;`).
- File-local functions and constants go in an anonymous namespace (clang-tidy
  `misc-use-internal-linkage`).
- Heterogeneous lookup: give `unordered_map<std::string, …>` a transparent hash and
  `std::equal_to<>` so `find(std::string_view)` doesn't allocate a temporary string.

## The "don't" list

| Don't | Do | Why |
|---|---|---|
| `new`/`delete`, `malloc`/`free` | `make_unique`, containers, values | leaks and double frees on every early return or throw |
| raw owning pointer members | `unique_ptr` member | the implicit copy constructor double-frees |
| C-style casts `(int)x` | `static_cast`, `std::bit_cast` | C casts silently become `reinterpret_cast` or cast away `const` |
| `using namespace std;` in headers | qualify names | pollutes every includer, causes ADL surprises |
| `#include <bits/stdc++.h>` | include what you use | libstdc++-only, slow to compile |
| `std::endl` in loops | `'\n'` | flushes the stream on every line |
| `NULL`, `0` for pointers | `nullptr` | overload resolution picks the integer overload |
| `volatile` for thread flags | `std::atomic<bool>` or `std::stop_token` | `volatile` gives no ordering or atomicity |
| `mutex.lock()`/`unlock()` | `std::scoped_lock` | an exception between them leaks the lock |
| `std::thread` + `detach()` | `std::jthread` | detached threads outlive their data and can't be stopped |
| `std::string_view` members/returns of locals | owning `std::string` | dangling |
| `strcpy`, `sprintf`, `gets` | `std::string`, `std::format` | no bounds |
| exceptions for control flow | `std::expected` | invisible in signatures, slow on the throw path |
| `shared_ptr` "to be safe" | `unique_ptr` + references | hides lifetime, atomic refcounts |
| `enable_if` SFINAE | concepts | unreadable errors |
| `-ffast-math` globally | nothing, or per-function after measuring | breaks NaN/inf handling everywhere |
