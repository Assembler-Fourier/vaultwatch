// Command gateway is VaultWatch's public edge: authentication, rate
// limiting, login-anomaly detection, and a thin authenticated reverse proxy
// to the internal risk-scoring engine.
package main

import (
	"context"
	"encoding/json"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/auth"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/events"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/ratelimit"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/service"
	"github.com/Assembler-Fourier/vaultwatch/gateway-go/internal/store"
)

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func clientIP(r *http.Request) string {
	if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
		return strings.TrimSpace(strings.Split(fwd, ",")[0])
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func main() {
	ctx := context.Background()

	jwtSecret := getenv("JWT_SECRET", "dev-only-insecure-secret-change-me")
	databaseURL := getenv("DATABASE_URL", "")
	redisURL := getenv("REDIS_URL", "redis://localhost:6379/0")
	engineURL := getenv("ENGINE_RUST_URL", "http://localhost:8081")
	port := getenv("PORT", "8080")

	var userStore interface {
		store.UserStore
		store.RefreshStore
	}
	if databaseURL != "" {
		pg, err := store.NewPostgresStore(ctx, databaseURL)
		if err != nil {
			log.Fatalf("connect postgres: %v", err)
		}
		userStore = pg
	} else {
		log.Println("DATABASE_URL not set - using in-memory store (state will not survive a restart)")
		userStore = store.NewMemoryStore()
	}

	var publisher events.Publisher
	if opt, err := redis.ParseURL(redisURL); err == nil {
		client := redis.NewClient(opt)
		if err := client.Ping(ctx).Err(); err != nil {
			log.Printf("redis not reachable (%v) - security events will not be published", err)
			publisher = events.NewRecordingPublisher()
		} else {
			publisher = events.NewRedisPublisher(client)
		}
	} else {
		log.Printf("invalid REDIS_URL (%v) - security events will not be published", err)
		publisher = events.NewRecordingPublisher()
	}

	tokens := auth.NewTokenIssuer(jwtSecret, 15*time.Minute)
	authSvc := service.NewAuthService(userStore, userStore, tokens, publisher, time.Now)
	limiter := ratelimit.NewLimiter(10, 0.5, time.Now) // 10 burst, refill 1 per 2s

	mux := http.NewServeMux()

	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	mux.HandleFunc("POST /auth/register", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Email    string `json:"email"`
			Password string `json:"password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
		if len(body.Password) < 10 {
			writeError(w, http.StatusBadRequest, "password must be at least 10 characters")
			return
		}
		user, err := authSvc.Register(ctx, body.Email, body.Password)
		if err != nil {
			writeError(w, http.StatusConflict, err.Error())
			return
		}
		writeJSON(w, http.StatusCreated, map[string]string{"id": user.ID, "email": user.Email})
	})

	mux.HandleFunc("POST /auth/login", func(w http.ResponseWriter, r *http.Request) {
		ip := clientIP(r)
		if !limiter.Allow("login:" + ip) {
			writeError(w, http.StatusTooManyRequests, "too many login attempts, slow down")
			return
		}

		var body struct {
			Email    string  `json:"email"`
			Password string  `json:"password"`
			Lat      float64 `json:"lat"`
			Lon      float64 `json:"lon"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}

		pair, err := authSvc.Login(ctx, service.LoginRequest{
			Email: body.Email, Password: body.Password,
			Lat: body.Lat, Lon: body.Lon, IP: ip,
		})
		if err != nil {
			writeError(w, http.StatusUnauthorized, "invalid credentials")
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{
			"access_token":  pair.AccessToken,
			"refresh_token": pair.RefreshToken,
		})
	})

	mux.HandleFunc("POST /auth/refresh", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			RefreshToken string `json:"refresh_token"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
		pair, err := authSvc.Refresh(ctx, body.RefreshToken)
		if err != nil {
			writeError(w, http.StatusUnauthorized, err.Error())
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{
			"access_token":  pair.AccessToken,
			"refresh_token": pair.RefreshToken,
		})
	})

	engineTarget, err := url.Parse(engineURL)
	if err != nil {
		log.Fatalf("invalid ENGINE_RUST_URL: %v", err)
	}
	proxy := httputil.NewSingleHostReverseProxy(engineTarget)
	mux.Handle("POST /v1/score", requireAuth(tokens, proxy))

	log.Printf("gateway-go listening on :%s (engine=%s)", port, engineURL)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatal(err)
	}
}

func requireAuth(tokens *auth.TokenIssuer, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		parts := strings.SplitN(header, " ", 2)
		if len(parts) != 2 || parts[0] != "Bearer" {
			writeError(w, http.StatusUnauthorized, "missing bearer token")
			return
		}
		if _, err := tokens.ParseAccessToken(parts[1]); err != nil {
			writeError(w, http.StatusUnauthorized, "invalid or expired token")
			return
		}
		next.ServeHTTP(w, r)
	})
}
