package link_test

import (
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/acme/links/internal/link"
)

func newTestMux(t *testing.T, store *memStore) *http.ServeMux {
	t.Helper()
	mux := http.NewServeMux()
	link.NewHandler(link.NewService(store), slog.New(slog.DiscardHandler)).Register(mux)
	return mux
}

func do(t *testing.T, h http.Handler, method, target, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequestWithContext(t.Context(), method, target, strings.NewReader(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestHTTP(t *testing.T) {
	t.Parallel()
	failing := newMemStore()
	failing.err = errors.New("db down: password=hunter2")

	tests := []struct {
		name       string
		store      *memStore
		method     string
		target     string
		body       string
		wantStatus int
		wantBody   string
	}{
		{"create", newMemStore(), "POST", "/api/links", `{"url":"https://go.dev","code":"godev"}`, 201, `"code":"godev"`},
		{"create generated", newMemStore(), "POST", "/api/links", `{"url":"https://go.dev"}`, 201, `"target_url":"https://go.dev"`},
		{"invalid url", newMemStore(), "POST", "/api/links", `{"url":"ftp://x"}`, 422, `"field":"url"`},
		{"unknown field", newMemStore(), "POST", "/api/links", `{"url":"https://go.dev","admin":true}`, 400, "invalid JSON"},
		{"duplicate key", newMemStore(), "POST", "/api/links", `{"url":"https://a.dev","url":"https://b.dev"}`, 400, "invalid JSON"},
		{"too large", newMemStore(), "POST", "/api/links", `{"url":"` + strings.Repeat("a", 2<<20) + `"}`, 413, "too large"},
		{"wrong method", newMemStore(), "DELETE", "/api/links", "", 405, ""},
		{"missing", newMemStore(), "GET", "/nope1", "", 404, "not found"},
		{"bad limit", newMemStore(), "GET", "/api/links?limit=x", "", 422, `"field":"limit"`},
		{"internal error hides details", failing, "GET", "/api/links", "", 500, "internal error"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			rec := do(t, newTestMux(t, tt.store), tt.method, tt.target, tt.body)
			body, _ := io.ReadAll(rec.Body)
			if rec.Code != tt.wantStatus || !strings.Contains(string(body), tt.wantBody) {
				t.Fatalf("%s %s = %d %s; want %d containing %q", tt.method, tt.target, rec.Code, body, tt.wantStatus, tt.wantBody)
			}
			if strings.Contains(string(body), "hunter2") {
				t.Fatal("internal error details leaked to the client")
			}
		})
	}
}

func TestRedirect(t *testing.T) {
	t.Parallel()
	mux := newTestMux(t, newMemStore())
	if rec := do(t, mux, "POST", "/api/links", `{"url":"https://go.dev/doc","code":"docs"}`); rec.Code != 201 {
		t.Fatalf("create = %d", rec.Code)
	}
	rec := do(t, mux, "GET", "/docs", "")
	if rec.Code != http.StatusFound || rec.Header().Get("Location") != "https://go.dev/doc" {
		t.Fatalf("GET /docs = %d Location=%q", rec.Code, rec.Header().Get("Location"))
	}
}
