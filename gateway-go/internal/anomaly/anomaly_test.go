package anomaly

import (
	"testing"
	"time"
)

func TestCheckImpossibleTravel_FlagsDublinToNewYorkInMinutes(t *testing.T) {
	base := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	last := GeoPoint{Lat: 53.3498, Lon: -6.2603, Time: base}
	current := GeoPoint{Lat: 40.7128, Lon: -74.0060, Time: base.Add(6 * time.Minute)}

	result := CheckImpossibleTravel(last, current)

	if !result.Impossible {
		t.Fatalf("expected impossible travel, got speed=%.0fkm/h dist=%.0fkm", result.SpeedKmh, result.DistanceKm)
	}
	if result.SpeedKmh <= ImpossibleTravelKmh {
		t.Fatalf("expected speed above threshold, got %.0f", result.SpeedKmh)
	}
}

func TestCheckImpossibleTravel_AllowsPlausibleCommute(t *testing.T) {
	base := time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)
	last := GeoPoint{Lat: 53.3498, Lon: -6.2603, Time: base} // Dublin city centre
	current := GeoPoint{Lat: 53.4264, Lon: -6.2499, Time: base.Add(45 * time.Minute)} // Dublin Airport

	result := CheckImpossibleTravel(last, current)

	if result.Impossible {
		t.Fatalf("expected plausible travel, got speed=%.0fkm/h", result.SpeedKmh)
	}
}

func TestCheckImpossibleTravel_ZeroOrNegativeElapsedTimeIsIgnored(t *testing.T) {
	base := time.Date(2026, 1, 1, 9, 0, 0, 0, time.UTC)
	last := GeoPoint{Lat: 53.3498, Lon: -6.2603, Time: base}
	current := GeoPoint{Lat: 40.7128, Lon: -74.0060, Time: base} // same instant, clock skew

	result := CheckImpossibleTravel(last, current)

	if result.Impossible {
		t.Fatalf("zero-duration comparisons should not be flagged")
	}
}

func TestBruteForceTracker_TriggersAtThreshold(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }
	tracker := NewBruteForceTracker(5*time.Minute, 3, clock)

	if triggered, count := tracker.RecordFailure("ip:1.2.3.4"); triggered || count != 1 {
		t.Fatalf("attempt 1: expected not triggered, count=1, got triggered=%v count=%d", triggered, count)
	}
	if triggered, count := tracker.RecordFailure("ip:1.2.3.4"); triggered || count != 2 {
		t.Fatalf("attempt 2: expected not triggered, count=2, got triggered=%v count=%d", triggered, count)
	}
	triggered, count := tracker.RecordFailure("ip:1.2.3.4")
	if !triggered || count != 3 {
		t.Fatalf("attempt 3: expected triggered, count=3, got triggered=%v count=%d", triggered, count)
	}
}

func TestBruteForceTracker_WindowExpiresOldFailures(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }
	tracker := NewBruteForceTracker(1*time.Minute, 3, clock)

	tracker.RecordFailure("ip:9.9.9.9")
	tracker.RecordFailure("ip:9.9.9.9")

	now = now.Add(2 * time.Minute) // outside the window now
	triggered, count := tracker.RecordFailure("ip:9.9.9.9")

	if triggered || count != 1 {
		t.Fatalf("expected stale failures to be pruned, got triggered=%v count=%d", triggered, count)
	}
}

func TestBruteForceTracker_ResetClearsHistory(t *testing.T) {
	now := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	clock := func() time.Time { return now }
	tracker := NewBruteForceTracker(5*time.Minute, 2, clock)

	tracker.RecordFailure("account:user@example.com")
	tracker.Reset("account:user@example.com")
	triggered, count := tracker.RecordFailure("account:user@example.com")

	if triggered || count != 1 {
		t.Fatalf("expected reset history, got triggered=%v count=%d", triggered, count)
	}
}
