package server_test

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/acme/links/internal/server"
)

type pinger struct{ err error }

func (p pinger) Ping(context.Context) error { return p.err }

type panicky struct{}

func (panicky) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /boom", func(http.ResponseWriter, *http.Request) { panic("boom") })
	mux.HandleFunc("POST /echo", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })
}

func TestHandler(t *testing.T) {
	t.Parallel()
	quiet := slog.New(slog.DiscardHandler)
	tests := []struct {
		name   string
		db     error
		method string
		path   string
		header map[string]string
		want   int
	}{
		{name: "up", method: "GET", path: "/up", want: 200},
		{name: "up with db down", db: errors.New("refused"), method: "GET", path: "/up", want: 503},
		{name: "panic becomes 500", method: "GET", path: "/boom", want: 500},
		{name: "same-origin POST", method: "POST", path: "/echo", header: map[string]string{"Sec-Fetch-Site": "same-origin"}, want: 204},
		{name: "non-browser POST", method: "POST", path: "/echo", want: 204},
		{name: "cross-site POST is CSRF", method: "POST", path: "/echo", header: map[string]string{"Sec-Fetch-Site": "cross-site"}, want: 403},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Parallel()
			h := server.New(quiet, pinger{tt.db}, panicky{})
			req := httptest.NewRequestWithContext(t.Context(), tt.method, tt.path, nil)
			for k, v := range tt.header {
				req.Header.Set(k, v)
			}
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != tt.want {
				t.Fatalf("%s %s = %d, want %d", tt.method, tt.path, rec.Code, tt.want)
			}
		})
	}
}

// TestServeGracefulShutdown proves an in-flight request finishes after the
// context is cancelled (what SIGTERM from kamal or docker stop does).
func TestServeGracefulShutdown(t *testing.T) {
	t.Parallel()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	started, release := make(chan struct{}), make(chan struct{})
	slow := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		close(started)
		<-release // hold the request open until shutdown has begun
		_, _ = w.Write([]byte("done"))
	})

	ctx, cancel := context.WithCancel(t.Context())
	served := make(chan error, 1)
	go func() { served <- server.Serve(ctx, ln, slow, slog.New(slog.DiscardHandler), 5*time.Second) }()

	status := make(chan int, 1)
	go func() {
		req, _ := http.NewRequestWithContext(context.Background(), http.MethodGet, "http://"+ln.Addr().String(), nil)
		r, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Error(err)
			status <- 0
			return
		}
		_ = r.Body.Close()
		status <- r.StatusCode
	}()
	<-started
	cancel()
	close(release)

	if err := <-served; err != nil {
		t.Fatalf("Serve returned %v, want nil after graceful shutdown", err)
	}
	if code := <-status; code != http.StatusOK {
		t.Fatalf("in-flight request status %d, want 200", code)
	}
}
