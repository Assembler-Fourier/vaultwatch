"""Stage 0: a cheap, always-on ML pre-filter.

This is the whole cost-control argument for the pipeline: an IsolationForest
scores every transaction in microseconds and for free. Only the ~5-10% it
flags as anomalous ever reach a Claude call. Stage 1 (Haiku) is cheap but
not free; stage 2/3 (Sonnet, with tool use) are the expensive, slow tiers
and should only ever see genuinely suspicious cases.
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import IsolationForest

from app.models import PreFilterVerdict, ScoringContext, Transaction
from app.synthetic import generate_baseline_features


def extract_features(tx: Transaction, ctx: ScoringContext) -> list[float]:
    if ctx.recent_amounts:
        mean = float(np.mean(ctx.recent_amounts))
        std = float(np.std(ctx.recent_amounts)) or 1.0
        z = (tx.amount - mean) / std
    else:
        z = 0.0

    hour = tx.timestamp.hour
    is_new_beneficiary = (
        1.0
        if tx.beneficiary_id and tx.beneficiary_id not in ctx.known_beneficiaries
        else 0.0
    )
    is_new_device = (
        1.0 if tx.device_id and tx.device_id not in ctx.known_devices else 0.0
    )

    return [tx.amount, z, float(hour), float(ctx.recent_count_last_hour), is_new_beneficiary, is_new_device]


class AnomalyPreFilter:
    """Wraps a scikit-learn IsolationForest fit on synthetic baseline
    "normal" behaviour. `contamination` is the expected fraction of
    training data considered anomalous - it calibrates the decision
    threshold, not a hard cap on how many live transactions can be flagged.
    """

    def __init__(self, contamination: float = 0.08, random_state: int = 7):
        self._model = IsolationForest(
            n_estimators=150,
            contamination=contamination,
            random_state=random_state,
        )
        self._fitted = False

    def fit(self, features: list[list[float]] | None = None) -> None:
        data = np.array(features if features is not None else generate_baseline_features())
        self._model.fit(data)
        self._fitted = True

    def score(self, tx: Transaction, ctx: ScoringContext) -> PreFilterVerdict:
        if not self._fitted:
            raise RuntimeError("AnomalyPreFilter.fit() must be called before score()")

        features = np.array([extract_features(tx, ctx)])
        # decision_function: higher = more normal, lower/negative = more anomalous.
        raw = float(self._model.decision_function(features)[0])
        prediction = int(self._model.predict(features)[0])  # -1 = anomaly, 1 = normal

        # Squash the raw decision score into a 0..1 "anomaly score" for
        # display purposes: 0 = clearly normal, 1 = clearly anomalous.
        anomaly_score = max(0.0, min(1.0, 0.5 - raw))

        return PreFilterVerdict(anomaly_score=anomaly_score, is_anomaly=prediction == -1)
