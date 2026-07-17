// Package store defines the persistence interfaces used by the auth
// service, plus an in-memory implementation for tests and a Postgres
// implementation for the running service.
package store

import (
	"context"
	"errors"
	"time"
)

var ErrNotFound = errors.New("not found")

type User struct {
	ID           string
	Email        string
	PasswordHash string
	LastLoginLat *float64
	LastLoginLon *float64
	LastLoginAt  *time.Time
}

type UserStore interface {
	CreateUser(ctx context.Context, email, passwordHash string) (*User, error)
	GetUserByEmail(ctx context.Context, email string) (*User, error)
	GetUserByID(ctx context.Context, id string) (*User, error)
	UpdateLastLogin(ctx context.Context, userID string, lat, lon float64, at time.Time) error
}

type RefreshToken struct {
	Hash      string
	UserID    string
	FamilyID  string
	Revoked   bool
	UsedAt    *time.Time
	ExpiresAt time.Time
}

type RefreshStore interface {
	Save(ctx context.Context, rt RefreshToken) error
	Get(ctx context.Context, hash string) (*RefreshToken, error)
	MarkUsed(ctx context.Context, hash string, at time.Time) error
	RevokeFamily(ctx context.Context, familyID string) error
}
