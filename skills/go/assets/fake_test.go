package link_test

import (
	"cmp"
	"context"
	"slices"
	"sync"
	"time"

	"github.com/acme/links/internal/link"
)

// memStore is an in-memory link.Store for unit and HTTP tests. The mutex
// makes it safe under t.Parallel and -race.
type memStore struct {
	mu    sync.Mutex
	links map[string]link.Link
	next  int64
	err   error // when set, every call fails with it
}

func newMemStore() *memStore { return &memStore{links: map[string]link.Link{}} }

func (m *memStore) Create(_ context.Context, code, target string) (link.Link, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.err != nil {
		return link.Link{}, m.err
	}
	if _, ok := m.links[code]; ok {
		return link.Link{}, link.ErrCodeTaken
	}
	m.next++
	l := link.Link{ID: m.next, Code: code, TargetURL: target, CreatedAt: time.Unix(m.next, 0).UTC()}
	m.links[code] = l
	return l, nil
}

func (m *memStore) ByCode(_ context.Context, code string) (link.Link, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.err != nil {
		return link.Link{}, m.err
	}
	l, ok := m.links[code]
	if !ok {
		return link.Link{}, link.ErrNotFound
	}
	return l, nil
}

func (m *memStore) List(_ context.Context, limit int) ([]link.Link, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.err != nil {
		return nil, m.err
	}
	all := slices.SortedFunc(func(yield func(link.Link) bool) {
		for _, l := range m.links {
			if !yield(l) {
				return
			}
		}
	}, func(a, b link.Link) int { return cmp.Compare(b.ID, a.ID) })
	return all[:min(limit, len(all))], nil
}
