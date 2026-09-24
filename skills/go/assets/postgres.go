package link

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/acme/links/internal/link/linkdb"
)

const uniqueViolation = "23505"

// PostgresStore implements Store with sqlc-generated queries over pgx.
type PostgresStore struct {
	q *linkdb.Queries
}

// NewPostgresStore wraps a pgxpool.Pool, pgx.Conn, or pgx.Tx.
func NewPostgresStore(db linkdb.DBTX) *PostgresStore {
	return &PostgresStore{q: linkdb.New(db)}
}

// Create inserts a link, mapping a unique violation to ErrCodeTaken.
func (s *PostgresStore) Create(ctx context.Context, code, targetURL string) (Link, error) {
	row, err := s.q.CreateLink(ctx, linkdb.CreateLinkParams{Code: code, TargetURL: targetURL})
	if pgErr, ok := errors.AsType[*pgconn.PgError](err); ok && pgErr.Code == uniqueViolation {
		return Link{}, ErrCodeTaken
	}
	if err != nil {
		return Link{}, fmt.Errorf("create link: %w", err)
	}
	return Link(row), nil
}

// ByCode returns ErrNotFound when no row matches.
func (s *PostgresStore) ByCode(ctx context.Context, code string) (Link, error) {
	row, err := s.q.GetLinkByCode(ctx, code)
	if errors.Is(err, pgx.ErrNoRows) {
		return Link{}, ErrNotFound
	}
	if err != nil {
		return Link{}, fmt.Errorf("get link %q: %w", code, err)
	}
	return Link(row), nil
}

// List returns up to limit links, newest first.
func (s *PostgresStore) List(ctx context.Context, limit int) ([]Link, error) {
	rows, err := s.q.ListLinks(ctx, int32(min(max(limit, 0), 1000)))
	if err != nil {
		return nil, fmt.Errorf("list links: %w", err)
	}
	links := make([]Link, len(rows))
	for i, r := range rows {
		links[i] = Link(r)
	}
	return links, nil
}
