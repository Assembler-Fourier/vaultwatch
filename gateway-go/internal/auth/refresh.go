package auth

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/base64"
	"fmt"
)

// GenerateRefreshToken returns a random opaque token (given to the client)
// and its SHA-256 hash (what we persist). We never store refresh tokens in
// plaintext: a database leak should not hand out live sessions.
func GenerateRefreshToken() (plain string, hash string, err error) {
	raw := make([]byte, 32)
	if _, err = rand.Read(raw); err != nil {
		return "", "", fmt.Errorf("generate refresh token: %w", err)
	}
	plain = base64.RawURLEncoding.EncodeToString(raw)
	hash = HashRefreshToken(plain)
	return plain, hash, nil
}

func HashRefreshToken(plain string) string {
	sum := sha256.Sum256([]byte(plain))
	return hex.EncodeToString(sum[:])
}
