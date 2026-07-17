from datetime import datetime, timezone

from app.models import ScoringContext, Transaction
from app.prefilter import AnomalyPreFilter


def make_context(**overrides) -> ScoringContext:
    base = dict(
        recent_amounts=[40.0, 45.0, 38.0, 42.0, 50.0, 44.0, 41.0],
        recent_count_last_hour=1,
        recent_sum_last_hour=42.0,
        known_beneficiaries=["ben_known"],
        known_devices=["dev_known"],
    )
    base.update(overrides)
    return ScoringContext(**base)


def make_tx(**overrides) -> Transaction:
    base = dict(
        id="tx_1",
        account_id="acct_1",
        amount=42.0,
        timestamp=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc),
        beneficiary_id="ben_known",
        device_id="dev_known",
    )
    base.update(overrides)
    return Transaction(**base)


def test_prefilter_flags_extreme_amount_outlier() -> None:
    prefilter = AnomalyPreFilter()
    prefilter.fit()

    normal = prefilter.score(make_tx(amount=42.0), make_context())
    outlier = prefilter.score(
        make_tx(amount=50000.0, beneficiary_id="ben_never_seen", device_id="dev_never_seen"),
        make_context(),
    )

    assert not normal.is_anomaly
    assert outlier.is_anomaly
    assert outlier.anomaly_score > normal.anomaly_score


def test_prefilter_raises_if_scored_before_fit() -> None:
    prefilter = AnomalyPreFilter()
    try:
        prefilter.score(make_tx(), make_context())
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
