# backend/analysis/signal_importance.py
"""
Signal importance engine — learns which morning readiness signals predict
execution quality for this specific athlete.

Two modes:
  Default weights   — used until ~60 matched sessions exist.
                      Based on published population-level evidence.
  Learned weights   — trained on athlete's own execution data once enough exists.
                      Uses ensemble of Pearson, Spearman, Random Forest, ElasticNet.

Output: a conflict assessment dict used by the morning decision pipeline
to decide whether to surface the conditional_alt alongside the primary session.

The assessment is transparent — it shows which signals drove the score,
their individual contributions, and whether weights are default or learned.
"""

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CONFIG_DIR = os.environ.get("SEASON_CONFIG_PATH", "/config/season.json")
_WEIGHTS_FILE = Path(os.path.dirname(_CONFIG_DIR or "/config")) / "signal_weights.json"

# Default weights — population evidence baseline
# Normalised to sum to 1.0
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "hrv_pct_vs_baseline": 0.28,
    "sleep_score":         0.20,
    "sleep_duration_hr":   0.12,
    "body_battery":        0.15,
    "resting_hr_vs_baseline": 0.10,
    "tsb":                 0.08,
    "prior_day_tss_ratio": 0.04,
    "all_day_stress":      0.03,
    "_default":            0.05,   # fallback for any unlisted signal
    "_source":             "default",
    "_session_count":      0,
}

# Minimum sessions before attempting to learn weights
_MIN_SESSIONS_FOR_LEARNING = 60


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess_signal_conflict(biometrics: Dict[str, Any], fitness_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate morning readiness signals and return a conflict assessment.

    biometrics keys:
      hrv_this_morning, hrv_7d_avg, sleep_score (0–1), sleep_duration_hr,
      body_battery (0–100), resting_hr, resting_hr_7d_avg, all_day_stress (0–100)

    fitness_state keys:
      tsb, prior_day_tss_ratio (optional)

    Returns:
      level:           clear | mild | significant | high
      composite_score: float 0–1
      signal_scores:   per-signal breakdown
      top_drivers:     names of top 3 contributing signals
      weights_source:  default | learned | partial
      show_alt:        bool — whether to surface the conditional_alt
    """
    weights = _load_weights()
    signals = _extract_signals(biometrics, fitness_state)

    signal_scores: Dict[str, Any] = {}
    weighted_suppression = 0.0
    total_weight = 0.0

    for name, value in signals.items():
        if value is None:
            continue
        weight = weights.get(name, weights.get("_default", 0.05))
        suppression = _score_suppression(name, value, biometrics)
        contribution = suppression * weight

        signal_scores[name] = {
            "value": round(value, 3) if isinstance(value, float) else value,
            "suppression": round(suppression, 3),
            "weight": round(weight, 3),
            "contribution": round(contribution, 3),
        }
        weighted_suppression += contribution
        total_weight += weight

    composite = weighted_suppression / total_weight if total_weight > 0 else 0.0

    level = _composite_to_level(composite)

    top_drivers = sorted(
        [(k, v["contribution"]) for k, v in signal_scores.items() if v["contribution"] > 0.02],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    hrv_available = biometrics.get("hrv_this_morning") is not None

    # Surface alt if: significant/high conflict, OR HRV missing (conservative guardrail)
    show_alt = level in ("significant", "high") or not hrv_available

    return {
        "level": level,
        "composite_score": round(composite, 3),
        "signal_scores": signal_scores,
        "top_drivers": [name for name, _ in top_drivers],
        "driver_detail": {name: signal_scores[name] for name, _ in top_drivers},
        "hrv_available": hrv_available,
        "weights_source": weights.get("_source", "default"),
        "session_count": weights.get("_session_count", 0),
        "show_alt": show_alt,
        "readout_line": _build_readout_line(level, top_drivers, hrv_available),
    }


def train_signal_weights(execution_records: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Train signal importance weights from matched execution records.

    execution_records: list of dicts each containing:
      morning biometrics snapshot + execution score (overall_execution float 0–1)

    Requires sklearn. Returns weights dict ready to save to disk.
    Falls back gracefully if sklearn is not installed.
    """
    if len(execution_records) < _MIN_SESSIONS_FOR_LEARNING:
        logger.info(
            "Only %d sessions — need %d to train weights. Using defaults.",
            len(execution_records), _MIN_SESSIONS_FOR_LEARNING
        )
        return _DEFAULT_WEIGHTS.copy()

    try:
        import numpy as np
        from scipy import stats
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.linear_model import ElasticNet
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        logger.warning("sklearn/scipy not available — cannot train signal weights. Using defaults.")
        return _DEFAULT_WEIGHTS.copy()

    signal_keys = [k for k in _DEFAULT_WEIGHTS if not k.startswith("_")]

    X_rows, y_rows = [], []
    for rec in execution_records:
        row = [rec.get(k) for k in signal_keys]
        if any(v is None for v in row):
            continue
        X_rows.append(row)
        y_rows.append(rec.get("overall_execution", 0.0))

    if len(X_rows) < 30:
        logger.warning("Only %d complete records after filtering — using defaults.", len(X_rows))
        return _DEFAULT_WEIGHTS.copy()

    X = np.array(X_rows, dtype=float)
    y = np.array(y_rows, dtype=float)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    importances: Dict[str, List[float]] = {k: [] for k in signal_keys}

    # Pearson correlation
    for i, k in enumerate(signal_keys):
        r, _ = stats.pearsonr(X[:, i], y)
        importances[k].append(max(abs(r), 0))

    # Spearman correlation
    for i, k in enumerate(signal_keys):
        r, _ = stats.spearmanr(X[:, i], y)
        importances[k].append(max(abs(r), 0))

    # Random Forest permutation importance
    try:
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_scaled, y)
        rf_imp = rf.feature_importances_
        for i, k in enumerate(signal_keys):
            importances[k].append(max(rf_imp[i], 0))
    except Exception as exc:
        logger.warning("Random Forest training failed: %s", exc)

    # ElasticNet coefficient magnitude
    try:
        en = ElasticNet(alpha=0.1, l1_ratio=0.5, max_iter=2000)
        en.fit(X_scaled, y)
        en_coef = abs(en.coef_)
        total_coef = sum(en_coef)
        for i, k in enumerate(signal_keys):
            importances[k].append(en_coef[i] / total_coef if total_coef > 0 else 0)
    except Exception as exc:
        logger.warning("ElasticNet training failed: %s", exc)

    # Average across methods and normalise
    raw_weights = {k: sum(vs) / len(vs) for k, vs in importances.items() if vs}
    total = sum(raw_weights.values())
    if total == 0:
        return _DEFAULT_WEIGHTS.copy()

    learned = {k: round(v / total, 4) for k, v in raw_weights.items()}
    learned["_source"] = "learned"
    learned["_session_count"] = len(X_rows)
    learned["_default"] = 0.03
    learned["_trained_date"] = date.today().isoformat()

    _save_weights(learned)
    logger.info("Signal weights trained from %d sessions and saved.", len(X_rows))
    return learned


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_weights() -> Dict[str, Any]:
    if _WEIGHTS_FILE.exists():
        try:
            return json.loads(_WEIGHTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _DEFAULT_WEIGHTS.copy()


def _save_weights(weights: Dict[str, Any]) -> None:
    try:
        _WEIGHTS_FILE.write_text(json.dumps(weights, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to save signal weights: %s", exc)


# ---------------------------------------------------------------------------
# Signal extraction and scoring
# ---------------------------------------------------------------------------

def _extract_signals(biometrics: Dict, fitness: Dict) -> Dict[str, Optional[float]]:
    hrv_today = biometrics.get("hrv_this_morning")
    hrv_baseline = biometrics.get("hrv_7d_avg")
    hrv_pct = None
    if hrv_today and hrv_baseline and hrv_baseline > 0:
        hrv_pct = ((hrv_today - hrv_baseline) / hrv_baseline) * 100

    rhr_today = biometrics.get("resting_hr")
    rhr_baseline = biometrics.get("resting_hr_7d_avg")
    rhr_delta = None
    if rhr_today and rhr_baseline and rhr_baseline > 0:
        rhr_delta = ((rhr_today - rhr_baseline) / rhr_baseline) * 100  # positive = elevated = worse

    return {
        "hrv_pct_vs_baseline":       hrv_pct,
        "sleep_score":               biometrics.get("sleep_score"),     # 0–1
        "sleep_duration_hr":         biometrics.get("sleep_duration_hr"),
        "body_battery":              biometrics.get("body_battery"),     # 0–100
        "resting_hr_vs_baseline":    rhr_delta,
        "tsb":                       fitness.get("tsb"),
        "prior_day_tss_ratio":       biometrics.get("prior_day_tss_ratio"),
        "all_day_stress":            biometrics.get("all_day_stress"),   # 0–100
    }


def _score_suppression(signal: str, value: float, biometrics: Dict) -> float:
    """
    Map signal value to suppression score 0–1.
    0 = fully normal / green. 1 = maximally suppressed / concerning.
    """
    if signal == "hrv_pct_vs_baseline":
        # Negative % = HRV below baseline = suppressed
        if value >= 0:
            return 0.0
        return min(abs(value) / 30.0, 1.0)   # -30% → 1.0

    if signal == "sleep_score":
        # 1.0 = perfect, 0 = terrible
        return max(0.0, 1.0 - value)

    if signal == "sleep_duration_hr":
        # Below 7hr starts to matter
        if value >= 7.5:
            return 0.0
        return min((7.5 - value) / 3.0, 1.0)

    if signal == "body_battery":
        # 100 = full, 0 = depleted
        if value >= 70:
            return 0.0
        return min((70 - value) / 70.0, 1.0)

    if signal == "resting_hr_vs_baseline":
        # Positive % = elevated RHR = worse
        if value <= 0:
            return 0.0
        return min(value / 20.0, 1.0)         # +20% → 1.0

    if signal == "tsb":
        # Very negative TSB = highly fatigued
        if value >= -10:
            return 0.0
        return min(abs(value + 10) / 30.0, 1.0)   # -40 → 1.0

    if signal == "prior_day_tss_ratio":
        # >1.2 means yesterday was significantly over plan → carry-forward fatigue
        if value is None or value <= 1.1:
            return 0.0
        return min((value - 1.1) / 0.5, 1.0)

    if signal == "all_day_stress":
        # 0–100 Garmin stress score
        if value < 50:
            return 0.0
        return min((value - 50) / 50.0, 1.0)

    return 0.0


def _composite_to_level(score: float) -> str:
    if score < 0.20:
        return "clear"
    if score < 0.45:
        return "mild"
    if score < 0.70:
        return "significant"
    return "high"


def _build_readout_line(level: str, top_drivers: List, hrv_available: bool) -> str:
    if not hrv_available:
        return "HRV reading missing — primary session with optional HR ceiling"
    if level == "clear":
        return "All signals green — go with primary"
    driver_names = [n.replace("_", " ") for n, _ in top_drivers[:2]]
    drivers_str = " and ".join(driver_names) if driver_names else "multiple signals"
    labels = {
        "mild": "Mild signal conflict",
        "significant": "Significant signal conflict",
        "high": "High signal conflict",
    }
    return f"{labels.get(level, 'Signal conflict')} — {drivers_str} below baseline. Alt available."
