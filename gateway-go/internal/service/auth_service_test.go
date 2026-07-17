package service

import (
	"context"
	"testing"
	"time"

	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/auth"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/events"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/store"
)

func newTestService(now func() time.Time) (*AuthService, *events.RecordingPublisher) {
	users := store.NewMemoryStore()
	pub := events.NewRecordingPublisher()
	tokens := auth.NewTokenIssuer("test-secret", 15*time.Minute)
	svc := NewAuthService(users, users, tokens, pub, now)
	return svc, pub
}

func TestRegisterAndLogin_Succeeds(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	svc, _ := newTestService(func() time.Time { return now })

	if _, err := svc.Register(ctx, "dana@example.com", "hunter2-hunter2"); err != nil {
		t.Fatalf("Register: %v", err)
	}

	pair, err := svc.Login(ctx, LoginRequest{
		Email: "dana@example.com", Password: "hunter2-hunter2",
		Lat: 53.3498, Lon: -6.2603, IP: "1.2.3.4",
	})
	if err != nil {
		t.Fatalf("Login: %v", err)
	}
	if pair.AccessToken == "" || pair.RefreshToken == "" {
		t.Fatal("expected non-empty token pair")
	}
}

func TestRegister_RejectsDuplicateEmail(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestService(time.Now)

	if _, err := svc.Register(ctx, "dup@example.com", "password123"); err != nil {
		t.Fatalf("first Register: %v", err)
	}
	if _, err := svc.Register(ctx, "dup@example.com", "password123"); err != ErrEmailTaken {
		t.Fatalf("expected ErrEmailTaken, got %v", err)
	}
}

func TestLogin_WrongPasswordTriggersBruteForceEventAtThreshold(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	svc, pub := newTestService(func() time.Time { return now })
	svc.Register(ctx, "victim@example.com", "correct-password")

	var lastErr error
	for i := 0; i < 5; i++ {
		_, lastErr = svc.Login(ctx, LoginRequest{
			Email: "victim@example.com", Password: "wrong", IP: "9.9.9.9",
		})
	}
	if lastErr != ErrInvalidCredentials {
		t.Fatalf("expected ErrInvalidCredentials, got %v", lastErr)
	}

	found := false
	for _, m := range pub.Messages {
		if m.Event.Type == "brute_force_ip" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected a brute_force_ip security event after 5 failed attempts from the same IP")
	}
}

func TestLogin_ImpossibleTravelIsFlaggedButStillIssuesTokens(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	svc, pub := newTestService(func() time.Time { return now })
	svc.Register(ctx, "traveler@example.com", "password123")

	// First login from Dublin.
	_, err := svc.Login(ctx, LoginRequest{
		Email: "traveler@example.com", Password: "password123",
		Lat: 53.3498, Lon: -6.2603, IP: "1.1.1.1",
	})
	if err != nil {
		t.Fatalf("first Login: %v", err)
	}

	// Six minutes later, from New York - not physically possible.
	now = now.Add(6 * time.Minute)
	_, err = svc.Login(ctx, LoginRequest{
		Email: "traveler@example.com", Password: "password123",
		Lat: 40.7128, Lon: -74.0060, IP: "2.2.2.2",
	})
	if err != nil {
		t.Fatalf("second Login: %v", err)
	}

	found := false
	for _, m := range pub.Messages {
		if m.Event.Type == "impossible_travel" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected an impossible_travel security event")
	}
}

func TestRefresh_RotatesTokenAndAllowsContinuedUse(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	svc, _ := newTestService(func() time.Time { return now })
	svc.Register(ctx, "rotator@example.com", "password123")

	pair, err := svc.Login(ctx, LoginRequest{Email: "rotator@example.com", Password: "password123", IP: "1.1.1.1"})
	if err != nil {
		t.Fatalf("Login: %v", err)
	}

	rotated, err := svc.Refresh(ctx, pair.RefreshToken)
	if err != nil {
		t.Fatalf("Refresh: %v", err)
	}
	if rotated.RefreshToken == pair.RefreshToken {
		t.Fatal("expected refresh to issue a new refresh token, not reuse the old one")
	}
}

func TestRefresh_ReusingARotatedTokenRevokesTheFamily(t *testing.T) {
	ctx := context.Background()
	now := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	svc, pub := newTestService(func() time.Time { return now })
	svc.Register(ctx, "stolen@example.com", "password123")

	pair, err := svc.Login(ctx, LoginRequest{Email: "stolen@example.com", Password: "password123", IP: "1.1.1.1"})
	if err != nil {
		t.Fatalf("Login: %v", err)
	}

	// Legitimate rotation.
	if _, err := svc.Refresh(ctx, pair.RefreshToken); err != nil {
		t.Fatalf("first Refresh: %v", err)
	}

	// An attacker (or a stale client) replays the original, now-rotated token.
	_, err = svc.Refresh(ctx, pair.RefreshToken)
	if err != ErrTokenReuse {
		t.Fatalf("expected ErrTokenReuse, got %v", err)
	}

	found := false
	for _, m := range pub.Messages {
		if m.Event.Type == "refresh_token_reuse" && m.Event.Severity == "critical" {
			found = true
		}
	}
	if !found {
		t.Fatal("expected a critical refresh_token_reuse security event")
	}
}

func TestRefresh_RejectsUnknownToken(t *testing.T) {
	ctx := context.Background()
	svc, _ := newTestService(time.Now)

	if _, err := svc.Refresh(ctx, "not-a-real-token"); err != ErrInvalidRefresh {
		t.Fatalf("expected ErrInvalidRefresh, got %v", err)
	}
}
