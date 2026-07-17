// Package ratelimit implements a simple per-key token bucket limiter, used
// to blunt brute-force and credential-stuffing traffic at the edge before
// it ever reaches the anomaly detectors or the database.
package ratelimit

import (
	"sync"
	"time"
)

type bucket struct {
	tokens float64
	last   time.Time
}

type Limiter struct {
	mu           sync.Mutex
	buckets      map[string]*bucket
	capacity     float64
	refillPerSec float64
	now          func() time.Time
}

func NewLimiter(capacity float64, refillPerSec float64, now func() time.Time) *Limiter {
	return &Limiter{
		buckets:      make(map[string]*bucket),
		capacity:     capacity,
		refillPerSec: refillPerSec,
		now:          now,
	}
}

// Allow consumes one token for key if available and reports whether the
// request should proceed.
func (l *Limiter) Allow(key string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()

	now := l.now()
	b, ok := l.buckets[key]
	if !ok {
		b = &bucket{tokens: l.capacity - 1, last: now}
		l.buckets[key] = b
		return true
	}

	elapsed := now.Sub(b.last).Seconds()
	if elapsed > 0 {
		b.tokens += elapsed * l.refillPerSec
		if b.tokens > l.capacity {
			b.tokens = l.capacity
		}
		b.last = now
	}

	if b.tokens < 1 {
		return false
	}
	b.tokens--
	return true
}
