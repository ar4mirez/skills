package retry_test

import (
	"context"
	"errors"
	"slices"
	"testing"
	"testing/synctest"
	"time"

	"github.com/acme/retry"
)

var errFlaky = errors.New("flaky")

func TestDelays(t *testing.T) {
	t.Parallel()
	p := retry.Policy{Attempts: 5, Base: time.Second, Max: 3 * time.Second}
	got := slices.Collect(p.Delays())
	want := []time.Duration{time.Second, 2 * time.Second, 3 * time.Second, 3 * time.Second}
	if !slices.Equal(got, want) {
		t.Fatalf("Delays() = %v, want %v", got, want)
	}
}

func TestDo(t *testing.T) {
	t.Parallel()
	errFatal := errors.New("bad request")
	tests := []struct {
		name      string
		failures  int   // calls that fail before success
		failWith  error // error returned by failing calls
		wantCalls int
		wantIs    error
	}{
		{name: "first try", failures: 0, wantCalls: 1},
		{name: "recovers", failures: 2, failWith: errFlaky, wantCalls: 3},
		{name: "exhausted", failures: 99, failWith: errFlaky, wantCalls: 5, wantIs: errFlaky},
		{name: "permanent stops", failures: 99, failWith: retry.Permanent(errFatal), wantCalls: 1, wantIs: errFatal},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			// synctest gives the bubble a fake clock: backoff sleeps finish
			// instantly and deterministically.
			synctest.Test(t, func(t *testing.T) {
				calls := 0
				start := time.Now()
				err := retry.Do(t.Context(), retry.Default, func(context.Context) error {
					calls++
					if calls <= tt.failures {
						return tt.failWith
					}
					return nil
				})
				if calls != tt.wantCalls {
					t.Errorf("calls = %d, want %d", calls, tt.wantCalls)
				}
				if !errors.Is(err, tt.wantIs) || (tt.wantIs == nil && err != nil) {
					t.Errorf("err = %v, want %v", err, tt.wantIs)
				}
				if elapsed := time.Since(start); elapsed > 16*time.Second {
					t.Errorf("fake time elapsed %v exceeds the policy's bound", elapsed)
				}
			})
		})
	}
}

func TestDoStopsOnCancel(t *testing.T) {
	t.Parallel()
	synctest.Test(t, func(t *testing.T) {
		ctx, cancel := context.WithTimeout(t.Context(), 150*time.Millisecond)
		defer cancel()
		p := retry.Policy{Attempts: 100, Base: time.Second, Max: time.Second}
		calls := 0
		err := retry.Do(ctx, p, func(context.Context) error { calls++; return errFlaky })
		if !errors.Is(err, context.DeadlineExceeded) || !errors.Is(err, errFlaky) {
			t.Fatalf("err = %v, want DeadlineExceeded wrapping the last error", err)
		}
		if calls > 2 {
			t.Fatalf("calls = %d after cancel, want at most 2", calls)
		}
	})
}

func TestInvalidPolicy(t *testing.T) {
	t.Parallel()
	err := retry.Do(t.Context(), retry.Policy{}, func(context.Context) error { return nil })
	if !errors.Is(err, retry.ErrInvalidPolicy) {
		t.Fatalf("err = %v, want ErrInvalidPolicy", err)
	}
}
