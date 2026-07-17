// Package anomaly implements login-security heuristics for VaultWatch's
// auth gateway: impossible-travel detection between consecutive logins, and
// sliding-window brute-force / credential-stuffing detection.
package anomaly

import (
	"math"
	"time"
)

const (
	earthRadiusKm = 6371.0
	// ImpossibleTravelKmh mirrors engine-rust's transaction-side threshold:
	// nothing legitimate moves faster than a commercial flight.
	ImpossibleTravelKmh = 900.0
)

// GeoPoint is a login's coordinates and the time it was observed.
type GeoPoint struct {
	Lat  float64
	Lon  float64
	Time time.Time
}

// TravelResult reports whether the transition between two logins implied a
// physically impossible speed.
type TravelResult struct {
	Impossible bool
	SpeedKmh   float64
	DistanceKm float64
}

func haversineKm(a, b GeoPoint) float64 {
	lat1, lon1 := a.Lat*math.Pi/180, a.Lon*math.Pi/180
	lat2, lon2 := b.Lat*math.Pi/180, b.Lon*math.Pi/180
	dlat := lat2 - lat1
	dlon := lon2 - lon1
	h := math.Pow(math.Sin(dlat/2), 2) + math.Cos(lat1)*math.Cos(lat2)*math.Pow(math.Sin(dlon/2), 2)
	return 2 * earthRadiusKm * math.Asin(math.Sqrt(h))
}

// CheckImpossibleTravel compares a new login's location against the
// account's last known login location. If the implied speed of travel
// exceeds ImpossibleTravelKmh, the credentials are very likely being used
// from two places (i.e. shared or stolen) rather than one traveling user.
func CheckImpossibleTravel(last, current GeoPoint) TravelResult {
	hours := current.Time.Sub(last.Time).Hours()
	if hours <= 0 {
		return TravelResult{}
	}
	dist := haversineKm(last, current)
	speed := dist / hours
	return TravelResult{
		Impossible: speed > ImpossibleTravelKmh,
		SpeedKmh:   speed,
		DistanceKm: dist,
	}
}
