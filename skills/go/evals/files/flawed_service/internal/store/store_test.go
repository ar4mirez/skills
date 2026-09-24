package store

import (
	"testing"
	"time"
)

func TestCacheExpiry(t *testing.T) {
	c := map[int]time.Time{1: time.Now()}
	time.Sleep(2 * time.Second)
	if time.Since(c[1]) < time.Second {
		t.Fatal("expected expiry")
	}
}
