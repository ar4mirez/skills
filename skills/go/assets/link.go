// Package link implements the URL-shortening domain: validation, code
// generation, and the rules for creating and resolving links. It knows
// nothing about HTTP or SQL; those live in http.go and postgres.go.
package link

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"
)

// Link is a short code that redirects to a target URL.
type Link struct {
	ID        int64     `json:"id"`
	Code      string    `json:"code"`
	TargetURL string    `json:"target_url"`
	CreatedAt time.Time `json:"created_at"`
}

// Sentinel errors: callers compare with errors.Is.
var (
	ErrNotFound  = errors.New("link not found")
	ErrCodeTaken = errors.New("link code already taken")
)

// ValidationError reports a bad input field. Callers extract it with
// errors.AsType[*ValidationError].
type ValidationError struct {
	Field  string
	Reason string
}

func (e *ValidationError) Error() string { return e.Field + ": " + e.Reason }

const (
	maxURLLen   = 2048
	minCodeLen  = 4
	maxCodeLen  = 32
	genCodeLen  = 8
	maxAttempts = 3
)

// Store persists links. It is declared here, by its consumer, so the
// service can be tested with an in-memory fake.
type Store interface {
	Create(ctx context.Context, code, targetURL string) (Link, error)
	ByCode(ctx context.Context, code string) (Link, error)
	List(ctx context.Context, limit int) ([]Link, error)
}

// Service holds the link rules. Construct it with NewService.
type Service struct {
	store   Store
	newCode func() string
}

// NewService returns a Service backed by store.
func NewService(store Store) *Service {
	return &Service{store: store, newCode: randomCode}
}

// Shorten validates rawURL and stores it under code, or under a random
// code when code is empty.
func (s *Service) Shorten(ctx context.Context, rawURL, code string) (Link, error) {
	target, err := NormalizeURL(rawURL)
	if err != nil {
		return Link{}, err
	}
	if code != "" {
		if err := ValidateCode(code); err != nil {
			return Link{}, err
		}
		return s.store.Create(ctx, code, target)
	}
	// Generated codes can collide; retry a few times before giving up.
	for range maxAttempts {
		l, err := s.store.Create(ctx, s.newCode(), target)
		if !errors.Is(err, ErrCodeTaken) {
			return l, err
		}
	}
	return Link{}, fmt.Errorf("generate code after %d attempts: %w", maxAttempts, ErrCodeTaken)
}

// Resolve returns the link for code, or ErrNotFound.
func (s *Service) Resolve(ctx context.Context, code string) (Link, error) {
	if err := ValidateCode(code); err != nil {
		return Link{}, ErrNotFound // an invalid code can never exist
	}
	return s.store.ByCode(ctx, code)
}

// Recent returns up to limit links, newest first. limit is clamped to 1..100.
func (s *Service) Recent(ctx context.Context, limit int) ([]Link, error) {
	return s.store.List(ctx, min(max(limit, 1), 100))
}

// NormalizeURL accepts absolute http(s) URLs with a host and no user
// info, and returns their canonical string form.
func NormalizeURL(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" || len(raw) > maxURLLen {
		return "", &ValidationError{Field: "url", Reason: fmt.Sprintf("must be 1-%d characters", maxURLLen)}
	}
	u, err := url.Parse(raw)
	if err != nil {
		return "", &ValidationError{Field: "url", Reason: "is not a valid URL"}
	}
	if u.Scheme != "http" && u.Scheme != "https" {
		return "", &ValidationError{Field: "url", Reason: "scheme must be http or https"}
	}
	if u.Hostname() == "" {
		return "", &ValidationError{Field: "url", Reason: "must include a host"}
	}
	if u.User != nil {
		// user:pass@host URLs are a classic phishing disguise.
		return "", &ValidationError{Field: "url", Reason: "must not contain user info"}
	}
	out := u.String()
	if len(out) > maxURLLen {
		return "", &ValidationError{Field: "url", Reason: fmt.Sprintf("must be 1-%d characters", maxURLLen)}
	}
	return out, nil
}

// ValidateCode checks a custom short code: 4-32 of [A-Za-z0-9_-].
func ValidateCode(code string) error {
	if len(code) < minCodeLen || len(code) > maxCodeLen {
		return &ValidationError{Field: "code", Reason: fmt.Sprintf("must be %d-%d characters", minCodeLen, maxCodeLen)}
	}
	for _, r := range code {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '-', r == '_':
		default:
			return &ValidationError{Field: "code", Reason: "may contain only letters, digits, '-' and '_'"}
		}
	}
	return nil
}

// randomCode returns an unguessable lowercase code from crypto/rand.
func randomCode() string {
	return strings.ToLower(rand.Text()[:genCodeLen])
}
