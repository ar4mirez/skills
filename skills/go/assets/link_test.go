package link_test

import (
	"context"
	"errors"
	"net/url"
	"testing"

	"github.com/acme/links/internal/link"
)

func TestNormalizeURL(t *testing.T) {
	t.Parallel()
	tests := []struct {
		name    string
		in      string
		want    string
		wantErr bool
	}{
		{name: "https", in: "https://go.dev/doc", want: "https://go.dev/doc"},
		{name: "trims space", in: "  http://example.com/a?b=c  ", want: "http://example.com/a?b=c"},
		{name: "empty", in: "", wantErr: true},
		{name: "relative", in: "/just/a/path", wantErr: true},
		{name: "javascript scheme", in: "javascript:alert(1)", wantErr: true},
		{name: "no host", in: "https:///path", wantErr: true},
		{name: "user info", in: "https://bank.com@evil.example/", wantErr: true},
		{name: "control char", in: "https://example.com/\x7f", wantErr: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			got, err := link.NormalizeURL(tt.in)
			if tt.wantErr {
				if _, ok := errors.AsType[*link.ValidationError](err); !ok {
					t.Fatalf("NormalizeURL(%q) error = %v, want *ValidationError", tt.in, err)
				}
				return
			}
			if err != nil || got != tt.want {
				t.Fatalf("NormalizeURL(%q) = %q, %v; want %q, nil", tt.in, got, err, tt.want)
			}
		})
	}
}

func TestValidateCode(t *testing.T) {
	t.Parallel()
	for code, ok := range map[string]bool{
		"go-dev": true, "A_b9": true, "abc": false, "has space": false,
		"ümlaut": false, "0123456789012345678901234567890123": false,
	} {
		if err := link.ValidateCode(code); (err == nil) != ok {
			t.Errorf("ValidateCode(%q) = %v, want ok=%v", code, err, ok)
		}
	}
}

func TestShorten(t *testing.T) {
	t.Parallel()
	ctx := t.Context()

	t.Run("custom code, then duplicate", func(t *testing.T) {
		t.Parallel()
		svc := link.NewService(newMemStore())
		l, err := svc.Shorten(ctx, "https://go.dev", "godev")
		if err != nil || l.Code != "godev" || l.TargetURL != "https://go.dev" {
			t.Fatalf("Shorten = %+v, %v", l, err)
		}
		if _, err := svc.Shorten(ctx, "https://go.dev", "godev"); !errors.Is(err, link.ErrCodeTaken) {
			t.Fatalf("duplicate err = %v, want ErrCodeTaken", err)
		}
	})

	t.Run("generated code", func(t *testing.T) {
		t.Parallel()
		svc := link.NewService(newMemStore())
		l, err := svc.Shorten(ctx, "https://go.dev", "")
		if err != nil {
			t.Fatal(err)
		}
		if err := link.ValidateCode(l.Code); err != nil {
			t.Fatalf("generated code %q invalid: %v", l.Code, err)
		}
	})

	t.Run("store failure is wrapped, not swallowed", func(t *testing.T) {
		t.Parallel()
		boom := errors.New("connection reset")
		store := newMemStore()
		store.err = boom
		_, err := link.NewService(store).Shorten(ctx, "https://go.dev", "")
		if !errors.Is(err, boom) {
			t.Fatalf("err = %v, want %v in chain", err, boom)
		}
	})

	t.Run("invalid code never hits the store", func(t *testing.T) {
		t.Parallel()
		_, err := link.NewService(newMemStore()).Resolve(ctx, "../etc")
		if !errors.Is(err, link.ErrNotFound) {
			t.Fatalf("err = %v, want ErrNotFound", err)
		}
	})
}

func TestRecentClampsLimit(t *testing.T) {
	t.Parallel()
	store := newMemStore()
	svc := link.NewService(store)
	for range 3 {
		if _, err := svc.Shorten(context.Background(), "https://go.dev", ""); err != nil {
			t.Fatal(err)
		}
	}
	got, err := svc.Recent(t.Context(), 0)
	if err != nil || len(got) != 1 {
		t.Fatalf("Recent(0) = %d links, %v; want 1 (clamped)", len(got), err)
	}
}

// FuzzNormalizeURL checks properties, not examples: accepted URLs are
// absolute http(s), and normalizing is idempotent.
func FuzzNormalizeURL(f *testing.F) {
	for _, seed := range []string{"https://go.dev", "http://a.b/c?d#e", "javascript:x", "https://u:p@h/", " "} {
		f.Add(seed)
	}
	f.Fuzz(func(t *testing.T, in string) {
		out, err := link.NormalizeURL(in)
		if err != nil {
			return
		}
		u, perr := url.Parse(out)
		if perr != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" {
			t.Fatalf("NormalizeURL(%q) = %q: not an absolute http(s) URL", in, out)
		}
		again, err := link.NormalizeURL(out)
		if err != nil || again != out {
			t.Fatalf("not idempotent: %q -> %q -> %q (%v)", in, out, again, err)
		}
	})
}

func BenchmarkNormalizeURL(b *testing.B) {
	b.ReportAllocs()
	for b.Loop() {
		if _, err := link.NormalizeURL("https://go.dev/doc/go1.27?utm_source=x#top"); err != nil {
			b.Fatal(err)
		}
	}
}
