package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// PostgresStore implements UserStore and RefreshStore against a real
// Postgres database. Schema is created idempotently on startup rather than
// through a separate migration tool, since the schema is small and stable
// enough that a migration framework would be pure ceremony here.
type PostgresStore struct {
	pool *pgxpool.Pool
}

func NewPostgresStore(ctx context.Context, databaseURL string) (*PostgresStore, error) {
	pool, err := pgxpool.New(ctx, databaseURL)
	if err != nil {
		return nil, err
	}
	s := &PostgresStore{pool: pool}
	if err := s.ensureSchema(ctx); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *PostgresStore) Close() {
	s.pool.Close()
}

func (s *PostgresStore) ensureSchema(ctx context.Context) error {
	_, err := s.pool.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS users (
			id UUID PRIMARY KEY,
			email TEXT UNIQUE NOT NULL,
			password_hash TEXT NOT NULL,
			last_login_lat DOUBLE PRECISION,
			last_login_lon DOUBLE PRECISION,
			last_login_at TIMESTAMPTZ,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);

		CREATE TABLE IF NOT EXISTS refresh_tokens (
			hash TEXT PRIMARY KEY,
			user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
			family_id UUID NOT NULL,
			revoked BOOLEAN NOT NULL DEFAULT false,
			used_at TIMESTAMPTZ,
			expires_at TIMESTAMPTZ NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now()
		);

		CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family_id ON refresh_tokens(family_id);
	`)
	return err
}

func (s *PostgresStore) CreateUser(ctx context.Context, email, passwordHash string) (*User, error) {
	id := uuid.NewString()
	_, err := s.pool.Exec(ctx,
		`INSERT INTO users (id, email, password_hash) VALUES ($1, $2, $3)`,
		id, email, passwordHash,
	)
	if err != nil {
		return nil, err
	}
	return &User{ID: id, Email: email, PasswordHash: passwordHash}, nil
}

func (s *PostgresStore) GetUserByEmail(ctx context.Context, email string) (*User, error) {
	row := s.pool.QueryRow(ctx,
		`SELECT id, email, password_hash, last_login_lat, last_login_lon, last_login_at
		 FROM users WHERE email = $1`, email,
	)
	var u User
	if err := row.Scan(&u.ID, &u.Email, &u.PasswordHash, &u.LastLoginLat, &u.LastLoginLon, &u.LastLoginAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &u, nil
}

func (s *PostgresStore) GetUserByID(ctx context.Context, id string) (*User, error) {
	row := s.pool.QueryRow(ctx,
		`SELECT id, email, password_hash, last_login_lat, last_login_lon, last_login_at
		 FROM users WHERE id = $1`, id,
	)
	var u User
	if err := row.Scan(&u.ID, &u.Email, &u.PasswordHash, &u.LastLoginLat, &u.LastLoginLon, &u.LastLoginAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &u, nil
}

func (s *PostgresStore) UpdateLastLogin(ctx context.Context, userID string, lat, lon float64, at time.Time) error {
	_, err := s.pool.Exec(ctx,
		`UPDATE users SET last_login_lat = $1, last_login_lon = $2, last_login_at = $3 WHERE id = $4`,
		lat, lon, at, userID,
	)
	return err
}

func (s *PostgresStore) Save(ctx context.Context, rt RefreshToken) error {
	_, err := s.pool.Exec(ctx,
		`INSERT INTO refresh_tokens (hash, user_id, family_id, revoked, used_at, expires_at)
		 VALUES ($1, $2, $3, $4, $5, $6)`,
		rt.Hash, rt.UserID, rt.FamilyID, rt.Revoked, rt.UsedAt, rt.ExpiresAt,
	)
	return err
}

func (s *PostgresStore) Get(ctx context.Context, hash string) (*RefreshToken, error) {
	row := s.pool.QueryRow(ctx,
		`SELECT hash, user_id, family_id, revoked, used_at, expires_at
		 FROM refresh_tokens WHERE hash = $1`, hash,
	)
	var rt RefreshToken
	if err := row.Scan(&rt.Hash, &rt.UserID, &rt.FamilyID, &rt.Revoked, &rt.UsedAt, &rt.ExpiresAt); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	return &rt, nil
}

func (s *PostgresStore) MarkUsed(ctx context.Context, hash string, at time.Time) error {
	_, err := s.pool.Exec(ctx, `UPDATE refresh_tokens SET used_at = $1 WHERE hash = $2`, at, hash)
	return err
}

func (s *PostgresStore) RevokeFamily(ctx context.Context, familyID string) error {
	_, err := s.pool.Exec(ctx, `UPDATE refresh_tokens SET revoked = true WHERE family_id = $1`, familyID)
	return err
}
