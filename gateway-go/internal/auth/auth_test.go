package auth

import (
	"testing"
	"time"
)

func TestHashAndVerifyPassword_RoundTrips(t *testing.T) {
	hash, err := HashPassword("correct horse battery staple")
	if err != nil {
		t.Fatalf("HashPassword: %v", err)
	}

	ok, err := VerifyPassword(hash, "correct horse battery staple")
	if err != nil {
		t.Fatalf("VerifyPassword: %v", err)
	}
	if !ok {
		t.Fatal("expected correct password to verify")
	}
}

func TestVerifyPassword_RejectsWrongPassword(t *testing.T) {
	hash, _ := HashPassword("correct horse battery staple")

	ok, err := VerifyPassword(hash, "wrong password")
	if err != nil {
		t.Fatalf("VerifyPassword: %v", err)
	}
	if ok {
		t.Fatal("expected wrong password to fail verification")
	}
}

func TestHashPassword_ProducesUniqueSaltsPerCall(t *testing.T) {
	h1, _ := HashPassword("same-password")
	h2, _ := HashPassword("same-password")
	if h1 == h2 {
		t.Fatal("expected different salts to produce different hashes for the same password")
	}
}

func TestTokenIssuer_IssueAndParseRoundTrips(t *testing.T) {
	issuer := NewTokenIssuer("test-secret", 15*time.Minute)

	token, err := issuer.IssueAccessToken("user-123", "person@example.com")
	if err != nil {
		t.Fatalf("IssueAccessToken: %v", err)
	}

	claims, err := issuer.ParseAccessToken(token)
	if err != nil {
		t.Fatalf("ParseAccessToken: %v", err)
	}
	if claims.UserID != "user-123" || claims.Email != "person@example.com" {
		t.Fatalf("unexpected claims: %+v", claims)
	}
}

func TestTokenIssuer_RejectsExpiredToken(t *testing.T) {
	issuer := NewTokenIssuer("test-secret", -1*time.Minute) // already expired
	token, err := issuer.IssueAccessToken("user-123", "person@example.com")
	if err != nil {
		t.Fatalf("IssueAccessToken: %v", err)
	}

	if _, err := issuer.ParseAccessToken(token); err == nil {
		t.Fatal("expected expired token to be rejected")
	}
}

func TestTokenIssuer_RejectsTokenSignedWithDifferentSecret(t *testing.T) {
	issuerA := NewTokenIssuer("secret-a", 15*time.Minute)
	issuerB := NewTokenIssuer("secret-b", 15*time.Minute)

	token, _ := issuerA.IssueAccessToken("user-123", "person@example.com")
	if _, err := issuerB.ParseAccessToken(token); err == nil {
		t.Fatal("expected token signed with a different secret to be rejected")
	}
}

func TestGenerateRefreshToken_HashIsDeterministicFromPlain(t *testing.T) {
	plain, hash, err := GenerateRefreshToken()
	if err != nil {
		t.Fatalf("GenerateRefreshToken: %v", err)
	}
	if HashRefreshToken(plain) != hash {
		t.Fatal("expected HashRefreshToken(plain) to match the returned hash")
	}
}

func TestGenerateRefreshToken_IsUniquePerCall(t *testing.T) {
	p1, _, _ := GenerateRefreshToken()
	p2, _, _ := GenerateRefreshToken()
	if p1 == p2 {
		t.Fatal("expected unique refresh tokens per call")
	}
}
