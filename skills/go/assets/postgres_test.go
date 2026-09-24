package link_test

import (
	"errors"
	"os"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/acme/links/db"
	"github.com/acme/links/internal/link"
)

// TestPostgresStore runs against a real Postgres (CI service container or a
// local one). Mocks can't catch SQL, constraint, or migration bugs.
//
//	TEST_DATABASE_URL=postgres://postgres:postgres@localhost:5432/links_test go test ./...
func TestPostgresStore(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("TEST_DATABASE_URL not set")
	}
	ctx := t.Context()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if err := db.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}

	// Each test runs in a transaction that is rolled back: no cleanup, no cross-test leaks.
	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tx.Rollback(ctx) })
	store := link.NewPostgresStore(tx)

	created, err := store.Create(ctx, "pgtest", "https://go.dev")
	if err != nil {
		t.Fatal(err)
	}
	got, err := store.ByCode(ctx, "pgtest")
	if err != nil || got.ID != created.ID || got.CreatedAt.IsZero() {
		t.Fatalf("ByCode = %+v, %v; want %+v", got, err, created)
	}
	if _, err := store.ByCode(ctx, "absent"); !errors.Is(err, link.ErrNotFound) {
		t.Fatalf("ByCode(absent) err = %v, want ErrNotFound", err)
	}
	links, err := store.List(ctx, 10)
	if err != nil || len(links) == 0 {
		t.Fatalf("List = %v, %v", links, err)
	}
	// Last: a failed statement aborts the transaction.
	if _, err := store.Create(ctx, "pgtest", "https://example.com"); !errors.Is(err, link.ErrCodeTaken) {
		t.Fatalf("duplicate err = %v, want ErrCodeTaken", err)
	}
}
