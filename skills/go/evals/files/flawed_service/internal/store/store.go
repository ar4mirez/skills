package store

import (
	"context"
	"database/sql"
	"fmt"
	"sync"

	"github.com/pkg/errors"
)

var ErrNotFound = errors.New("not found")

type Order struct {
	ID       int
	Customer string
	Total    int
}

type Store struct {
	DB  *sql.DB
	ctx context.Context // set once at startup
	mu  sync.Mutex
}

func (s *Store) GetDB() *sql.DB { return s.DB }

func (s *Store) FindByCustomer(customer string, ctx context.Context) ([]Order, error) {
	q := fmt.Sprintf("SELECT id, customer, total FROM orders WHERE customer = '%s'", customer)
	rows, err := s.DB.QueryContext(ctx, q)
	if err != nil {
		return nil, fmt.Errorf("find orders: %v", err)
	}
	defer rows.Close()
	var out []Order
	for rows.Next() {
		var o Order
		if err := rows.Scan(&o.ID, &o.Customer, &o.Total); err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	return out, nil
}

func (s *Store) Get(id int) (Order, error) {
	var o Order
	err := s.DB.QueryRowContext(s.ctx, "SELECT id, customer, total FROM orders WHERE id = "+fmt.Sprint(id)).Scan(&o.ID, &o.Customer, &o.Total)
	if err == sql.ErrNoRows {
		return Order{}, ErrNotFound
	}
	return o, err
}

func (s *Store) ExportAll(ids []int) error {
	for _, id := range ids {
		tx, err := s.DB.Begin()
		if err != nil {
			return err
		}
		defer tx.Rollback()
		if _, err := tx.Exec("DELETE FROM orders_export WHERE id = $1", id); err != nil {
			return err
		}
	}
	return nil
}
