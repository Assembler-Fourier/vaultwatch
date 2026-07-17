// Package service composes the auth, anomaly-detection, storage and event
// packages into the actual login/refresh business logic used by the HTTP
// handlers in cmd/gateway.
package service

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"

	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/anomaly"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/auth"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/events"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/store"
)

var (
	ErrInvalidCredentials = errors.New("invalid credentials")
	ErrEmailTaken         = errors.New("email already registered")
	ErrTokenReuse         = errors.New("refresh token reuse detected, session revoked")
	ErrInvalidRefresh     = errors.New("invalid or expired refresh token")
)

const SecurityEventsChannel = "security.events"

type AuthService struct {
	Users         store.UserStore
	RefreshTokens store.RefreshStore
	Tokens        *auth.TokenIssuer
	Publisher     events.Publisher

	bruteForceByIP      *anomaly.BruteForceTracker
	bruteForceByAccount *anomaly.BruteForceTracker

	RefreshTTL time.Duration
	Now        func() time.Time
}

func NewAuthService(users store.UserStore, refresh store.RefreshStore, tokens *auth.TokenIssuer, publisher events.Publisher, now func() time.Time) *AuthService {
	if now == nil {
		now = time.Now
	}
	return &AuthService{
		Users:               users,
		RefreshTokens:       refresh,
		Tokens:              tokens,
		Publisher:           publisher,
		bruteForceByIP:      anomaly.NewBruteForceTracker(5*time.Minute, 5, now),
		bruteForceByAccount: anomaly.NewBruteForceTracker(15*time.Minute, 8, now),
		RefreshTTL:          7 * 24 * time.Hour,
		Now:                 now,
	}
}

type LoginRequest struct {
	Email    string
	Password string
	Lat      float64
	Lon      float64
	IP       string
}

type TokenPair struct {
	AccessToken  string
	RefreshToken string
}

func (s *AuthService) Register(ctx context.Context, email, password string) (*store.User, error) {
	if _, err := s.Users.GetUserByEmail(ctx, email); err == nil {
		return nil, ErrEmailTaken
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		return nil, err
	}
	return s.Users.CreateUser(ctx, email, hash)
}

func (s *AuthService) Login(ctx context.Context, req LoginRequest) (*TokenPair, error) {
	ipKey := "ip:" + req.IP
	accountKey := "account:" + req.Email

	user, err := s.Users.GetUserByEmail(ctx, req.Email)
	if err != nil {
		s.recordFailure(ctx, ipKey, accountKey, req.Email)
		return nil, ErrInvalidCredentials
	}

	ok, err := auth.VerifyPassword(user.PasswordHash, req.Password)
	if err != nil || !ok {
		s.recordFailure(ctx, ipKey, accountKey, req.Email)
		return nil, ErrInvalidCredentials
	}

	s.bruteForceByIP.Reset(ipKey)
	s.bruteForceByAccount.Reset(accountKey)

	if user.LastLoginAt != nil && user.LastLoginLat != nil && user.LastLoginLon != nil {
		result := anomaly.CheckImpossibleTravel(
			anomaly.GeoPoint{Lat: *user.LastLoginLat, Lon: *user.LastLoginLon, Time: *user.LastLoginAt},
			anomaly.GeoPoint{Lat: req.Lat, Lon: req.Lon, Time: s.Now()},
		)
		if result.Impossible {
			s.publish(ctx, events.SecurityEvent{
				Type:      "impossible_travel",
				AccountID: user.ID,
				Severity:  "high",
				Detail: map[string]any{
					"speed_kmh":    result.SpeedKmh,
					"distance_km":  result.DistanceKm,
					"prior_login":  user.LastLoginAt,
				},
			})
		}
	}

	if err := s.Users.UpdateLastLogin(ctx, user.ID, req.Lat, req.Lon, s.Now()); err != nil {
		return nil, err
	}

	return s.issueTokenPair(ctx, user.ID, user.Email, uuid.NewString())
}

func (s *AuthService) recordFailure(ctx context.Context, ipKey, accountKey, email string) {
	if triggered, count := s.bruteForceByIP.RecordFailure(ipKey); triggered {
		s.publish(ctx, events.SecurityEvent{
			Type:     "brute_force_ip",
			Severity: "critical",
			Detail:   map[string]any{"ip_key": ipKey, "failure_count": count},
		})
	}
	if triggered, count := s.bruteForceByAccount.RecordFailure(accountKey); triggered {
		s.publish(ctx, events.SecurityEvent{
			Type:     "brute_force_account",
			Severity: "critical",
			Detail:   map[string]any{"email": email, "failure_count": count},
		})
	}
}

func (s *AuthService) Refresh(ctx context.Context, plainToken string) (*TokenPair, error) {
	hash := auth.HashRefreshToken(plainToken)
	rt, err := s.RefreshTokens.Get(ctx, hash)
	if err != nil {
		return nil, ErrInvalidRefresh
	}

	if rt.Revoked || rt.UsedAt != nil {
		// A token that was already rotated away (or explicitly revoked) is
		// being replayed - the most likely explanation is that it leaked.
		// Burning the whole family forces re-authentication everywhere.
		_ = s.RefreshTokens.RevokeFamily(ctx, rt.FamilyID)
		s.publish(ctx, events.SecurityEvent{
			Type:      "refresh_token_reuse",
			AccountID: rt.UserID,
			Severity:  "critical",
			Detail:    map[string]any{"family_id": rt.FamilyID},
		})
		return nil, ErrTokenReuse
	}

	if s.Now().After(rt.ExpiresAt) {
		return nil, ErrInvalidRefresh
	}

	if err := s.RefreshTokens.MarkUsed(ctx, hash, s.Now()); err != nil {
		return nil, err
	}

	user, err := s.Users.GetUserByID(ctx, rt.UserID)
	if err != nil {
		return nil, err
	}

	return s.issueTokenPair(ctx, user.ID, user.Email, rt.FamilyID)
}

func (s *AuthService) issueTokenPair(ctx context.Context, userID, email, familyID string) (*TokenPair, error) {
	access, err := s.Tokens.IssueAccessToken(userID, email)
	if err != nil {
		return nil, err
	}

	plain, hash, err := auth.GenerateRefreshToken()
	if err != nil {
		return nil, err
	}

	if err := s.RefreshTokens.Save(ctx, store.RefreshToken{
		Hash:      hash,
		UserID:    userID,
		FamilyID:  familyID,
		ExpiresAt: s.Now().Add(s.RefreshTTL),
	}); err != nil {
		return nil, err
	}

	return &TokenPair{AccessToken: access, RefreshToken: plain}, nil
}

func (s *AuthService) publish(ctx context.Context, event events.SecurityEvent) {
	if s.Publisher == nil {
		return
	}
	event.Timestamp = s.Now().UTC().Format(time.RFC3339)
	_ = s.Publisher.Publish(ctx, SecurityEventsChannel, event)
}
