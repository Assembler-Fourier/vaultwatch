package store

import (
	"context"
	"sync"
	"time"

	"github.com/google/uuid"
)

// MemoryStore is a thread-safe, in-memory implementation of UserStore and
// RefreshStore, used in tests so the auth service's logic can be verified
// without a running Postgres instance.
type MemoryStore struct {
	mu      sync.Mutex
	users   map[string]*User // keyed by email
	byID    map[string]*User // keyed by ID
	tokens  map[string]*RefreshToken
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		users:  make(map[string]*User),
		byID:   make(map[string]*User),
		tokens: make(map[string]*RefreshToken),
	}
}

func (m *MemoryStore) CreateUser(_ context.Context, email, passwordHash string) (*User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	u := &User{ID: uuid.NewString(), Email: email, PasswordHash: passwordHash}
	m.users[email] = u
	m.byID[u.ID] = u
	return u, nil
}

func (m *MemoryStore) GetUserByEmail(_ context.Context, email string) (*User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	u, ok := m.users[email]
	if !ok {
		return nil, ErrNotFound
	}
	cp := *u
	return &cp, nil
}

func (m *MemoryStore) GetUserByID(_ context.Context, id string) (*User, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	u, ok := m.byID[id]
	if !ok {
		return nil, ErrNotFound
	}
	cp := *u
	return &cp, nil
}

func (m *MemoryStore) UpdateLastLogin(_ context.Context, userID string, lat, lon float64, at time.Time) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	u, ok := m.byID[userID]
	if !ok {
		return ErrNotFound
	}
	u.LastLoginLat = &lat
	u.LastLoginLon = &lon
	u.LastLoginAt = &at
	return nil
}

func (m *MemoryStore) Save(_ context.Context, rt RefreshToken) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := rt
	m.tokens[rt.Hash] = &cp
	return nil
}

func (m *MemoryStore) Get(_ context.Context, hash string) (*RefreshToken, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	rt, ok := m.tokens[hash]
	if !ok {
		return nil, ErrNotFound
	}
	cp := *rt
	return &cp, nil
}

func (m *MemoryStore) MarkUsed(_ context.Context, hash string, at time.Time) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	rt, ok := m.tokens[hash]
	if !ok {
		return ErrNotFound
	}
	rt.UsedAt = &at
	return nil
}

func (m *MemoryStore) RevokeFamily(_ context.Context, familyID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, rt := range m.tokens {
		if rt.FamilyID == familyID {
			rt.Revoked = true
		}
	}
	return nil
}
