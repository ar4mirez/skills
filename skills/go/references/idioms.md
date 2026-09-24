# Idioms and style

Effective Go, the Go Code Review Comments wiki, and the Google Go style guide,
condensed to the rules agents most often get wrong. Code samples compile under
Go 1.27.

## Contents
- Naming
- Errors
- Resource management
- API design
- Generics
- Iterators
- Modern stdlib you should reach for
- The "don't" list

## Naming

- Package names are short, lowercase, single words, with no underscores and
  no plurals (`link`, not `links_pkg`). Don't stutter: `link.Service`, not
  `link.LinkService`.
- MixedCaps only. Initialisms keep one case: `URL`, `ID`, `HTTPClient`,
  `userID`. (sqlc's `rename:` fixes generated `TargetUrl` to `TargetURL`.)
- Getters drop `Get`: `u.Name()`, with setter `u.SetName()`.
- Interfaces with one method are named for the method plus `-er`
  (`Pinger`, `Router`).
- Short names for short scopes (`i`, `r`, `w`, `ctx`, `err`); descriptive
  names for package-level identifiers and exported APIs.
- Receiver names are one or two letters, the same on every method, and never
  `this` or `self`.
- Errors: variables are `ErrXxx`, types are `XxxError`, and messages are
  lowercase with no trailing punctuation ("link not found").

## Errors

```go
var ErrNotFound = errors.New("link not found")          // sentinel: callers branch on it

type ValidationError struct{ Field, Reason string }     // typed: callers need fields
func (e *ValidationError) Error() string { return e.Field + ": " + e.Reason }

// Wrap with context on the way up; %w keeps the chain inspectable.
if err != nil {
	return Link{}, fmt.Errorf("get link %q: %w", code, err)
}

// Inspect.
if errors.Is(err, link.ErrNotFound) { ... }
if ve, ok := errors.AsType[*link.ValidationError](err); ok { ... }   // 1.26+
```

- **Wrap or return, and handle once.** Logging and then returning the same
  error duplicates it in the logs. The top of the call stack (the handler,
  `main`) logs it.
- **Add context the caller doesn't have** (the key, the operation). Don't
  prefix "failed to" or "error:" at every level.
- **Use `%w` only for errors that are part of your API.** Wrapping a driver
  error exposes it as your contract. The store in the template maps
  `pgx.ErrNoRows` to `link.ErrNotFound`, so callers never import pgx.
- `errors.Join(a, b)` and `fmt.Errorf("...: %w, %w", a, b)` both wrap
  several errors.
- `panic` only for programmer errors (an impossible `switch` default, a
  `Must` helper for package-level regexps and templates). Recover only at
  goroutine or request boundaries, as the `recoverer` middleware does, and
  re-panic `http.ErrAbortHandler`.
- Never compare `err.Error()` strings, and never `==` a wrapped error. The
  exception: `io.EOF` straight from `Read`, which is unwrapped by contract.

## Resource management

- `defer x.Close()` right after acquiring it, once the error is checked.
- For writable files, the `Close` error matters:

```go
func writeFile(path string, data []byte) (err error) {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, f.Close()) }()
	_, err = f.Write(data)
	return err
}
```

- **Don't `defer` in a loop.** Deferred calls run when the function returns,
  so the loop holds every file or transaction open. Move the body into a
  function.
- Always close `resp.Body` (and drain it if you want the connection reused).
  pgx rows close on full iteration; call `rows.Close()` via `defer` anyway,
  and check `rows.Err()`.
- Use `t.Cleanup`, `t.TempDir`, and `t.Context` in tests.
- `os.Root` (1.24+) confines file access to a directory: use it when paths
  come from users.

## API design

- **Accept interfaces, return concrete types.** Declare the interface where
  it's *used*, with only the methods used (`server.Pinger` needs only
  `Ping`). A `*pgxpool.Pool` satisfies it with no adapter.
- **Make the zero value useful** (`sync.Mutex`, `bytes.Buffer`,
  `http.CrossOriginProtection`) or provide one constructor, `NewX`.
- **Options:** start with a config struct. Use functional options only for
  libraries with many rarely-used knobs.
- **Synchronous APIs.** Return results; let the caller add goroutines.
  Exported functions that start goroutines must document how to stop them.
- `context.Context` first, `ctx` by name, never in a struct field, and never
  nil (use `context.TODO()` while migrating).
- Return `(T, error)` with the zero `T` on error; don't return a half-filled
  value with an error.
- Slices and maps passed in may be retained by the caller: copy them
  (`slices.Clone`, `maps.Clone`) if you store them.
- Document every exported identifier with a full sentence starting with its
  name.

## Generics

Use type parameters when the code is **the same for every type**:
containers, `slices`/`maps`-style helpers, and typed wrappers such as
`atomic.Pointer[T]`. Don't use them to abstract behavior (use an interface)
or "just in case".

```go
func Map[S ~[]E, E, R any](s S, f func(E) R) []R {
	out := make([]R, 0, len(s))
	for _, v := range s {
		out = append(out, f(v))
	}
	return out
}
```

- Constraints: `any`, `comparable`, `cmp.Ordered`, or `~T` unions.
- Go 1.27 allows generic **methods** (not in interfaces). Prefer a
  top-level generic function unless the method reads much better.
- Go 1.26 allows self-referential constraints
  (`type Adder[A Adder[A]] interface{ Add(A) A }`).

## Iterators

Range-over-func (1.23+): `iter.Seq[V]` is `func(yield func(V) bool)`.
Return one when callers may stop early or when materializing a slice would
be wasteful. `retry.Policy.Delays()` in the assets is a real example.

```go
func (p Policy) Delays() iter.Seq[time.Duration] {
	return func(yield func(time.Duration) bool) {
		d := p.Base
		for range p.Attempts - 1 {
			if !yield(min(d, p.Max)) {   // stop when the consumer breaks
				return
			}
			d = min(d*2, p.Max)
		}
	}
}
got := slices.Collect(p.Delays())
```

- Always honor a `false` from `yield`; ignoring it panics at runtime.
- The stdlib speaks iterators: `maps.Keys`, `slices.Sorted(maps.Keys(m))`,
  `strings.SplitSeq`, `strings.Lines`, `bytes.FieldsSeq`, and
  `reflect.Type.Fields()` (1.26).
- Don't return an iterator from something that must hold a lock or a DB
  row cursor unless you document that the caller must drain or break it.

## Modern stdlib you should reach for

`cmp.Or` (first non-zero value), `min`/`max` builtins, `slices` and `maps`,
`for i := range n`, `strings.Cut`/`CutPrefix`/`CutLast` (1.27),
`crypto/rand.Text()` for tokens, `uuid.NewV7()` (1.27) for sortable IDs,
`sync.OnceValue`, `atomic.Int64` over `atomic.AddInt64`, `errors.AsType`,
`new(expr)` (1.26), `t.Context()`, `os.Root`, `net/netip`, `unique.Make`
for interning, and `weak.Pointer` for caches. `go fix ./...` rewrites most
older forms automatically.

## The "don't" list

- Don't use `pkg/`, `util`, or `common`. Don't split one concept into
  `models/`, `services/`, `repositories/` layer packages; group by domain.
- Don't create interfaces before a second implementation or a test needs
  them, and don't return interfaces from constructors.
- Don't use `init()` for anything that can fail or touches I/O.
- Don't keep mutable package-level state (DB handles, config, loggers). Pass
  dependencies in.
- Don't use `interface{}`/`any` where a concrete type or generic works.
- Don't ignore errors silently. `_ = x` needs a comment on why it's safe.
- Don't `panic` across package boundaries, and don't `log.Fatal` outside
  `main`.
- Don't pass `*string` or `*int` just for optionality in internal APIs; use
  the zero value, `omitzero`, or an `ok bool`.
- Don't embed types in exported structs just to save typing; embedding
  exports the embedded methods as your API.
- Don't write getters and setters for plain data; exported fields are fine.
- Don't write `else` after `return`; keep the happy path unindented.
- Don't reach for reflection or code generation before plain code.
- Don't use `github.com/pkg/errors`, logrus, `io/ioutil`, or `lib/pq`. They
  have stdlib or maintained replacements.

Sources: https://go.dev/doc/effective_go, https://go.dev/wiki/CodeReviewComments,
https://google.github.io/styleguide/go/, https://go.dev/blog/range-functions,
https://go.dev/blog/go1.13-errors
