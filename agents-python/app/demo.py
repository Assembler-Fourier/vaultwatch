"""Explicit synthetic scenarios. Takeover exercises the real Go -> Redis -> Python path."""

import asyncio
import math
import os
import secrets
import random
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from app.models import ScoringContext, Transaction
from app.synthetic import (
    DUBLIN,
    LONDON,
    NEW_YORK,
    SYDNEY,
    account_profile,
    build_scoring_context,
)

CITIES = {"Dublin": DUBLIN, "London": LONDON, "New York": NEW_YORK, "Sydney": SYDNEY}


class DemoRequest(BaseModel):
    scenario: Literal["normal", "review", "unusual", "sanctions", "takeover"] = "normal"
    amount: float | None = Field(default=None, gt=0, le=1000000)
    origin: Literal["Dublin", "London", "New York", "Sydney"] = "Dublin"
    destination: Literal["Dublin", "London", "New York", "Sydney"] = "Sydney"


def balanced_batch(rng=None) -> list[DemoRequest]:
    """Fixed coverage, shuffled order. Risk outcomes still come from the real pipeline."""
    rng = rng or random.SystemRandom()
    requests = [DemoRequest(scenario="normal", amount=amount, origin=city, destination=city)
                for amount, city in zip([45, 50, 55, 60, 65], ["Dublin", "London", "New York", "Sydney", "Dublin"])]
    requests.extend([
        DemoRequest(scenario="review", amount=60, origin="Dublin", destination="Dublin"),
        DemoRequest(scenario="review", amount=65, origin="London", destination="London"),
        DemoRequest(scenario="unusual", amount=4200, origin="Dublin", destination="Sydney"),
        DemoRequest(scenario="sanctions", amount=4200, origin="Dublin", destination="London"),
        DemoRequest(scenario="takeover", amount=4200, origin="Dublin", destination="Sydney"),
    ])
    rng.shuffle(requests)
    return requests


def distance_km(origin, destination):
    lat1, lon1, lat2, lon2 = map(math.radians, (*origin, *destination))
    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


async def create_scenario(request: DemoRequest, orchestrator):
    # Pick a repeatable account with a representative normal baseline.
    account_id = next(
        f"acct_demo_{i}"
        for i in range(1000)
        if 40 <= account_profile(f"acct_demo_{i}").typical_amount <= 65
    )
    origin = CITIES[request.origin]
    destination_name = (
        request.origin if request.scenario in {"normal", "review"} else request.destination
    )
    destination = CITIES[destination_name]
    login_evidence = []
    if request.scenario == "takeover":
        if origin == destination:
            raise ValueError(
                "Choose different origin and payment locations for the takeover scenario."
            )
        gateway = os.getenv("GATEWAY_GO_URL", "http://gateway-go:8080")
        email, password = (
            f"demo-{uuid4().hex}@example.invalid",
            secrets.token_urlsafe(24),
        )
        async with httpx.AsyncClient(base_url=gateway, timeout=15) as client:
            response = await client.post(
                "/auth/register", json={"email": email, "password": password}
            )
            response.raise_for_status()
            account_id = response.json()["id"]
            for name, point in [
                (request.origin, origin),
                (destination_name, destination),
            ]:
                response = await client.post(
                    "/auth/login",
                    json={
                        "email": email,
                        "password": password,
                        "lat": point[0],
                        "lon": point[1],
                    },
                )
                response.raise_for_status()
                # Access and refresh tokens stay in this local request, never in reports.
                login_evidence.append(
                    {
                        "location": name,
                        "lat": point[0],
                        "lon": point[1],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "Go authentication service",
                    }
                )
        for _ in range(60):
            if orchestrator._recent_security_event(account_id):
                break
            await asyncio.sleep(0.05)
        else:
            raise RuntimeError(
                "Go logins succeeded but their security event did not arrive through Redis."
            )
    profile = account_profile(account_id)
    now = datetime.now(timezone.utc)
    risky = request.scenario not in {"normal", "review"}
    amount = (
        request.amount
        if request.amount is not None
        else (4200.0 if risky else profile.typical_amount)
    )
    tx = Transaction(
        id=f"tx_{uuid4().hex[:12]}",
        account_id=account_id,
        amount=amount,
        timestamp=now,
        lat=destination[0],
        lon=destination[1],
        beneficiary_id="ben_demo_new" if risky else profile.known_beneficiaries[0],
        beneficiary_name="Victor Krantz Holdings"
        if request.scenario == "sanctions"
        else "North Quay Supplies",
        device_id="dev_demo_new" if request.scenario != "normal" else profile.known_devices[0],
    )
    ctx = build_scoring_context(account_id, amount)
    if request.scenario == "review":
        # Moderate evidence: a new device and a burst of small payments, without travel or a watchlist hit.
        ctx["recent_count_last_hour"] = 5
        ctx["recent_sum_last_hour"] = amount * 4
    ctx["last_location"] = {
        "lat": origin[0],
        "lon": origin[1],
        "timestamp": (now - timedelta(hours=1)).isoformat(),
    }
    km = distance_km(origin, destination)
    review = {
        "scenario": request.scenario,
        "source": "Synthetic local scenario",
        "origin": {"name": request.origin, **ctx["last_location"]},
        "current_location": {
            "name": destination_name,
            "lat": tx.lat,
            "lon": tx.lon,
            "timestamp": tx.timestamp.isoformat(),
        },
        "distance_km": round(km, 1),
        "elapsed_minutes": 60,
        "implied_speed_kmh": round(km, 1),
        "baseline_average": round(
            sum(ctx["recent_amounts"]) / len(ctx["recent_amounts"]), 2
        ),
        "new_device": tx.device_id not in ctx["known_devices"],
        "new_beneficiary": tx.beneficiary_id not in ctx["known_beneficiaries"],
        "login_evidence": login_evidence,
        "location_note": "Locations are explicit synthetic coordinates, not IP geolocation. Payment history uses a one-hour interval; Go logins have their own actual timestamps.",
    }
    return tx, ScoringContext(**ctx), review
