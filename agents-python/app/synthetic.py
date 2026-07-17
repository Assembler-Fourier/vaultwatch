"""Synthetic data generation.

Every account, transaction, entity graph and sanctions-list entry in
VaultWatch is fabricated by this module using a seeded RNG. Nothing here
represents a real person, business, or financial record - that's a hard
requirement for a public demo that runs with a live LLM key.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

DUBLIN = (53.3498, -6.2603)
LONDON = (51.5072, -0.1276)
NEW_YORK = (40.7128, -74.0060)
SYDNEY = (-33.8688, 151.2093)
CITIES = [DUBLIN, LONDON, NEW_YORK, SYDNEY]

# A deliberately small, obviously-fake watchlist used only to demonstrate
# the investigator agent's `check_sanctions_list` tool call.
SYNTHETIC_SANCTIONS_LIST = {
    "victor krantz holdings",
    "ashgrove trading fzco",
    "meridian bulk logistics",
}


def _rng_for(seed_key: str) -> random.Random:
    """Deterministic per-key RNG so the same account_id always yields the
    same synthetic history within a process, without a shared global seed
    that would make every account look identical."""
    digest = hashlib.sha256(seed_key.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


@dataclass
class AccountProfile:
    account_id: str
    home_city: tuple[float, float]
    typical_amount: float
    known_beneficiaries: list[str] = field(default_factory=list)
    known_devices: list[str] = field(default_factory=list)


def account_profile(account_id: str) -> AccountProfile:
    rng = _rng_for(account_id)
    home = rng.choice(CITIES)
    typical = round(rng.uniform(20, 200), 2)
    beneficiaries = [f"ben_{rng.randint(1000, 9999)}" for _ in range(rng.randint(1, 4))]
    devices = [f"dev_{rng.randint(1000, 9999)}"]
    return AccountProfile(account_id, home, typical, beneficiaries, devices)


def generate_transaction_history(account_id: str, n: int = 20) -> list[dict]:
    """Synthetic prior transactions for an account, used both to build a
    ScoringContext and as the investigator agent's `get_transaction_history`
    tool result."""
    profile = account_profile(account_id)
    rng = _rng_for(account_id + ":history")
    history = []
    for i in range(n):
        amount = max(1.0, round(rng.gauss(profile.typical_amount, profile.typical_amount * 0.25), 2))
        history.append(
            {
                "id": f"tx_hist_{account_id}_{i}",
                "amount": amount,
                "beneficiary_id": rng.choice(profile.known_beneficiaries),
                "device_id": profile.known_devices[0],
            }
        )
    return history


def generate_entity_graph(account_id: str) -> dict:
    """A synthetic graph of accounts linked to this one (shared device,
    shared beneficiary, or shared IP block in a real system). Used by the
    investigator agent to reason about ring-like fraud patterns."""
    rng = _rng_for(account_id + ":graph")
    linked = [f"acct_{rng.randint(10000, 99999)}" for _ in range(rng.randint(0, 3))]
    return {
        "account_id": account_id,
        "linked_accounts": linked,
        "shared_device_count": len(linked),
    }


def check_sanctions_list(name: str) -> dict:
    hit = name.strip().lower() in SYNTHETIC_SANCTIONS_LIST
    return {"query": name, "hit": hit, "list": "vaultwatch-synthetic-watchlist-v1"}


def generate_baseline_features(n: int = 400, seed: int = 42) -> list[list[float]]:
    """Feature vectors representing "normal" account behaviour, used to fit
    the stage-0 IsolationForest pre-filter at startup. Features:
    [amount, z_score_vs_history, hour_of_day, recent_count_last_hour,
     is_new_beneficiary, is_new_device]
    """
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        amount = max(1.0, rng.gauss(60, 30))
        z = rng.gauss(0, 1)
        hour = rng.randint(0, 23)
        count = rng.choice([0, 1, 1, 2, 2, 3])
        new_ben = 1.0 if rng.random() < 0.05 else 0.0
        new_dev = 1.0 if rng.random() < 0.02 else 0.0
        rows.append([amount, z, hour, count, new_ben, new_dev])
    return rows


def build_scoring_context(
    account_id: str,
    current_amount: float,
    last_seen: datetime | None = None,
) -> dict:
    """Assembles a ScoringContext-shaped dict from synthetic history, for
    passing to engine-rust's /v1/score and to the prefilter's feature
    extraction. `last_seen` defaults to an hour before "now" so a normal
    transaction never trips the impossible-travel rule; the demo
    transaction generator overrides it to mint genuinely anomalous cases."""
    profile = account_profile(account_id)
    history = generate_transaction_history(account_id, n=12)
    amounts = [h["amount"] for h in history]
    last_seen = last_seen or (datetime.now(timezone.utc) - timedelta(hours=1))
    return {
        "recent_amounts": amounts,
        "recent_count_last_hour": 1,
        "recent_sum_last_hour": current_amount,
        "known_beneficiaries": profile.known_beneficiaries,
        "known_devices": profile.known_devices,
        "last_location": {
            "lat": profile.home_city[0],
            "lon": profile.home_city[1],
            "timestamp": last_seen.isoformat(),
        },
    }


def generate_demo_transaction(force_risky: bool = False, account_id: str | None = None) -> dict:
    """Builds a full synthetic Transaction dict (matching app.models.Transaction)
    for the live demo feed. With force_risky=True, deliberately stacks the
    amount-outlier, new-beneficiary and impossible-travel rules so the
    pipeline has something worth escalating."""
    rng = random.Random()
    account_id = account_id or f"acct_{rng.randint(10000, 99999)}"
    profile = account_profile(account_id)
    now = datetime.now(timezone.utc)

    if force_risky:
        far_city = rng.choice([c for c in CITIES if c != profile.home_city]) or NEW_YORK
        return {
            "id": f"tx_{uuid.uuid4().hex[:12]}",
            "account_id": account_id,
            "amount": round(profile.typical_amount * rng.uniform(15, 40), 2),
            "currency": "EUR",
            "timestamp": now.isoformat(),
            "lat": far_city[0],
            "lon": far_city[1],
            "beneficiary_id": f"ben_{rng.randint(100000, 999999)}",  # never in known_beneficiaries
            "device_id": f"dev_{rng.randint(100000, 999999)}",  # never in known_devices
        }

    return {
        "id": f"tx_{uuid.uuid4().hex[:12]}",
        "account_id": account_id,
        "amount": max(1.0, round(rng.gauss(profile.typical_amount, profile.typical_amount * 0.2), 2)),
        "currency": "EUR",
        "timestamp": now.isoformat(),
        "lat": profile.home_city[0],
        "lon": profile.home_city[1],
        "beneficiary_id": rng.choice(profile.known_beneficiaries),
        "device_id": profile.known_devices[0],
    }
