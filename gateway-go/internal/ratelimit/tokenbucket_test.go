package ratelimit

import (
	"testing"
	"time"
)

func TestLimiter_AllowsUpToCapacityThenBlocks(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }
	l := NewLimiter(3, 1, clock) // 3 tokens, refill 1/sec

	for i := 0; i < 3; i++ {
		if !l.Allow("ip:1.2.3.4") {
			t.Fatalf("expected request %d to be allowed within capacity", i+1)
		}
	}
	if l.Allow("ip:1.2.3.4") {
		t.Fatal("expected 4th immediate request to be blocked")
	}
}

func TestLimiter_RefillsOverTime(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }
	l := NewLimiter(1, 1, clock) // 1 token, refill 1/sec

	if !l.Allow("ip:5.6.7.8") {
		t.Fatal("expected first request to be allowed")
	}
	if l.Allow("ip:5.6.7.8") {
		t.Fatal("expected immediate second request to be blocked")
	}

	now = now.Add(2 * time.Second)
	if !l.Allow("ip:5.6.7.8") {
		t.Fatal("expected request to be allowed after refill window")
	}
}

func TestLimiter_TracksKeysIndependently(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }
	l := NewLimiter(1, 1, clock)

	if !l.Allow("ip:1.1.1.1") {
		t.Fatal("expected first key's first request to be allowed")
	}
	if !l.Allow("ip:2.2.2.2") {
		t.Fatal("expected second key to have its own independent bucket")
	}
}
