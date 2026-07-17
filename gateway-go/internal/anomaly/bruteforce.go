package anomaly

import (
	"sync"
	"time"
)

// BruteForceTracker counts failed-login events in a sliding window, keyed
// by an arbitrary string (typically "ip:1.2.3.4" or "account:<email>"). It
// is deliberately storage-agnostic and in-memory: the gateway is expected
// to run as a small number of replicas behind a shared rate limiter, and a
// brief loss of state on restart is an acceptable trade-off for not taking
// a hard Redis dependency on the hot path of every failed login.
type BruteForceTracker struct {
	mu        sync.Mutex
	window    time.Duration
	threshold int
	now       func() time.Time
	events    map[string][]time.Time
}

// NewBruteForceTracker builds a tracker that flags a key once it has seen
// `threshold` failures within `window`. `now` is injectable for tests; pass
// time.Now in production.
func NewBruteForceTracker(window time.Duration, threshold int, now func() time.Time) *BruteForceTracker {
	return &BruteForceTracker{
		window:    window,
		threshold: threshold,
		now:       now,
		events:    make(map[string][]time.Time),
	}
}

// RecordFailure registers a failed login attempt for key and reports
// whether the threshold has now been reached within the window.
func (b *BruteForceTracker) RecordFailure(key string) (triggered bool, count int) {
	b.mu.Lock()
	defer b.mu.Unlock()

	now := b.now()
	cutoff := now.Add(-b.window)

	kept := b.events[key][:0]
	for _, t := range b.events[key] {
		if t.After(cutoff) {
			kept = append(kept, t)
		}
	}
	kept = append(kept, now)
	b.events[key] = kept

	count = len(kept)
	return count >= b.threshold, count
}

// Reset clears failure history for a key, e.g. after a successful login.
func (b *BruteForceTracker) Reset(key string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	delete(b.events, key)
}
