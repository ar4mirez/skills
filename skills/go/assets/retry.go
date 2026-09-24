// Package retry calls an operation until it succeeds, using capped
// exponential backoff with full jitter. It honors context cancellation
// and stops early on errors marked Permanent.
package retry

import (
	"context"
	"errors"
	"fmt"
	"iter"
	"math/rand/v2"
	"time"
)

// Policy configures Do. The zero value is not useful; start from Default.
type Policy struct {
	Attempts int           // total calls, including the first (>= 1)
	Base     time.Duration // delay before the second call
	Max      time.Duration // cap for any single delay
}

// Default suits calls to a nearby network service.
var Default = Policy{Attempts: 5, Base: 100 * time.Millisecond, Max: 5 * time.Second}

// ErrInvalidPolicy is returned by Do for a policy that cannot run.
var ErrInvalidPolicy = errors.New("retry: invalid policy")

type permanentError struct{ err error }

func (e *permanentError) Error() string { return e.err.Error() }
func (e *permanentError) Unwrap() error { return e.err }

// Permanent marks err as not worth retrying; Do returns it unwrapped at once.
func Permanent(err error) error {
	if err == nil {
		return nil
	}
	return &permanentError{err: err}
}

// Delays yields the un-jittered delay before each retry: Base, 2*Base, ...
// capped at Max, Attempts-1 values in total.
func (p Policy) Delays() iter.Seq[time.Duration] {
	return func(yield func(time.Duration) bool) {
		d := p.Base
		for range p.Attempts - 1 {
			if !yield(min(d, p.Max)) {
				return
			}
			d = min(d*2, p.Max) // keep doubling bounded so it never overflows
		}
	}
}

// Do calls op until it returns nil, returns a Permanent error, the attempts
// run out, or ctx is done. The returned error wraps the last failure, so
// errors.Is and errors.AsType see through it.
func Do(ctx context.Context, p Policy, op func(context.Context) error) error {
	if p.Attempts < 1 || p.Base <= 0 || p.Max < p.Base {
		return fmt.Errorf("%w: %+v", ErrInvalidPolicy, p)
	}
	err := call(ctx, op)
	if err == nil || isPermanent(err) {
		return unwrapPermanent(err)
	}
	for d := range p.Delays() {
		t := time.NewTimer(rand.N(d) + 1) //nolint:gosec // jitter, not a secret: full jitter in [1ns, d]
		select {
		case <-ctx.Done():
			t.Stop()
			return fmt.Errorf("retry: %w (last error: %w)", context.Cause(ctx), err)
		case <-t.C:
		}
		if err = call(ctx, op); err == nil || isPermanent(err) {
			return unwrapPermanent(err)
		}
	}
	return fmt.Errorf("retry: %d attempts failed: %w", p.Attempts, err)
}

func call(ctx context.Context, op func(context.Context) error) error {
	if err := ctx.Err(); err != nil {
		return Permanent(context.Cause(ctx))
	}
	return op(ctx)
}

func isPermanent(err error) bool {
	_, ok := errors.AsType[*permanentError](err)
	return ok
}

func unwrapPermanent(err error) error {
	if pe, ok := errors.AsType[*permanentError](err); ok {
		return pe.err
	}
	return err
}
