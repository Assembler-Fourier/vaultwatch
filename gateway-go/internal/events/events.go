// Package events publishes security signals from the gateway (impossible
// travel, brute force, refresh-token reuse) onto a Redis channel that
// agents-python subscribes to, so financial-risk and account-security
// signals can be correlated into a single fused alert.
package events

import (
	"context"
	"encoding/json"
	"sync"

	"github.com/redis/go-redis/v9"
)

type SecurityEvent struct {
	Type      string         `json:"type"`
	AccountID string         `json:"account_id,omitempty"`
	Severity  string         `json:"severity"`
	Detail    map[string]any `json:"detail"`
	Timestamp string         `json:"timestamp"`
}

type Publisher interface {
	Publish(ctx context.Context, channel string, event SecurityEvent) error
}

// RedisPublisher publishes to a real Redis pub/sub channel.
type RedisPublisher struct {
	client *redis.Client
}

func NewRedisPublisher(client *redis.Client) *RedisPublisher {
	return &RedisPublisher{client: client}
}

func (p *RedisPublisher) Publish(ctx context.Context, channel string, event SecurityEvent) error {
	payload, err := json.Marshal(event)
	if err != nil {
		return err
	}
	return p.client.Publish(ctx, channel, payload).Err()
}

// RecordingPublisher captures published events in memory for tests instead
// of requiring a live Redis instance.
type RecordingPublisher struct {
	mu       sync.Mutex
	Messages []struct {
		Channel string
		Event   SecurityEvent
	}
}

func NewRecordingPublisher() *RecordingPublisher {
	return &RecordingPublisher{}
}

func (p *RecordingPublisher) Publish(_ context.Context, channel string, event SecurityEvent) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.Messages = append(p.Messages, struct {
		Channel string
		Event   SecurityEvent
	}{Channel: channel, Event: event})
	return nil
}
