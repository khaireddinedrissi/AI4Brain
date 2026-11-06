"""Transparent detection and handling for the six CISTAC challenge anomalies.

These are coaching safeguards, not clinical diagnoses. Thresholds are conservative,
configurable defaults and all decisions expose their evidence.
"""
from statistics import mean

DIMENSIONS = ("WM", "AT", "PS", "SP")
DIMENSION_NAMES = {"WM": "working memory", "AT": "attention",
                   "PS": "problem solving", "SP": "processing speed"}


def detect_button_masher(response_times, accuracy, minimum_samples=3,
                         minimum_median_seconds=0.8, max_accuracy=60):
    times = [float(x) for x in (response_times or []) if _finite_nonnegative(x)]
    if len(times) < minimum_samples:
        return {"detected": False, "status": "insufficient_data",
                "reason": "At least three valid response-time observations are required."}
    fast = sum(t < minimum_median_seconds for t in times) / len(times)
    low_accuracy = float(accuracy) <= max_accuracy
    detected = fast >= 0.7 and low_accuracy
    return {"detected": detected, "status": "high_uncertainty" if detected else "clear",
            "fast_response_ratio": round(fast, 3), "median_response_seconds": round(_median(times), 3),
            "reason": ("Rapid responses coincide with low accuracy; suppress ability conclusions and ask whether the user is rushing or distracted."
                       if detected else "No combined rapid-response/high-error pattern crossed the configured threshold.")}


def detect_plateau(history, minimum_sessions=4, tolerance=2.0):
    vals = [float(x) for x in (history or []) if _finite_number(x)]
    if len(vals) < minimum_sessions:
        return {"detected": False, "status": "insufficient_data",
                "reason": f"Need at least {minimum_sessions} comparable session scores."}
    recent = vals[-minimum_sessions:]
    spread = max(recent) - min(recent)
    detected = spread <= tolerance
    return {"detected": detected, "status": "plateau" if detected else "progress_or_variation",
            "window": len(recent), "score_spread": round(spread, 2),
            "reason": ("Scores have stagnated; propose a different task format or strategy."
                       if detected else "Recent scores vary beyond the plateau tolerance.")}


def explain_recommendation(dimension_scores, recommendation):
    scores = {k: v for k, v in (dimension_scores or {}).items()
              if k in DIMENSIONS and isinstance(v, (int, float)) and _finite_number(v)}
    target = recommendation if recommendation in DIMENSIONS else None
    if not scores or not target or target not in scores:
        return {"explainable": False, "reason": "There is not enough measured dimension data to justify this recommendation."}
    lowest = min(scores, key=scores.get)
    return {"explainable": True, "dimension": target, "observed_score": scores[target],
            "comparison": "lowest measured dimension" if target == lowest else "not the lowest measured dimension",
            "evidence": {k: scores[k] for k in sorted(scores)},
            "reason": (f"{DIMENSION_NAMES[target].title()} is the lowest measured dimension ({scores[target]:g}/100)."
                       if target == lowest else
                       f"{DIMENSION_NAMES[target].title()} was selected, but {DIMENSION_NAMES[lowest]} is lower ({scores[lowest]:g}/100); show the additional plan/objective factor before claiming it is the weakest skill.")}


def detect_pushback(message):
    text = str(message or "").lower()
    terms = ("i disagree", "not accurate", "that's wrong", "that is wrong",
             "poor performance was due", "i was distracted", "environmental distraction",
             "not my ability", "i was interrupted", "i don't agree", "i do not agree")
    found = next((term for term in terms if term in text), None)
    return {"detected": bool(found), "evidence": found,
            "handling": ("Acknowledge the user's context, mark this result as uncertain, invite a retest, and increase collaboration evidence; do not argue or silently overwrite the profile."
                         if found else "No explicit disagreement detected.")}


def guard_prediction(message):
    text = str(message or "")
    lower = text.lower()
    asks_future = any(x in lower for x in ("next month", "will my score", "predict", "forecast", "exactly"))
    if asks_future:
        return {"guarded": True, "response": ("I can't know your exact future cognitive score. Any projection would be an estimate, "
                "not a certainty; it should be shown as a range with a confidence interval and updated as more sessions are recorded.")}
    return {"guarded": False, "response": None}


def detect_asymmetry(dimension_scores, gap_threshold=20):
    scores = {k: float(v) for k, v in (dimension_scores or {}).items()
              if k in DIMENSIONS and _finite_number(v)}
    if len(scores) < 2:
        return {"detected": False, "status": "insufficient_data",
                "reason": "At least two measured cognitive dimensions are required."}
    strongest, weakest = max(scores, key=scores.get), min(scores, key=scores.get)
    gap = scores[strongest] - scores[weakest]
    return {"detected": gap >= gap_threshold, "gap": round(gap, 2),
            "strongest": strongest, "weakest": weakest,
            "plan": {"focus": weakest, "maintenance": strongest},
            "reason": (f"Uneven profile: focus on {DIMENSION_NAMES[weakest]} and maintain {DIMENSION_NAMES[strongest]}."
                       if gap >= gap_threshold else "No large split between measured dimensions was detected.")}


def analyze(payload):
    """Run the six named challenge checks on an explicit, auditable test payload."""
    payload = payload if isinstance(payload, dict) else {}
    scores = payload.get("dimension_scores") or {}
    return {
        "button_masher": detect_button_masher(payload.get("response_times"), payload.get("accuracy", 100)),
        "stagnation_plateau": detect_plateau(payload.get("score_history")),
        "why_audit": explain_recommendation(scores, payload.get("recommended_dimension")),
        "pushback": detect_pushback(payload.get("user_message", "")),
        "fortune_teller": guard_prediction(payload.get("user_message", "")),
        "asymmetrical_mind": detect_asymmetry(scores),
        "disclaimer": "Practice-support signals only; not a clinical or validated cognitive diagnosis."
    }


def _finite_number(value):
    try:
        import math
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _finite_nonnegative(value):
    return _finite_number(value) and float(value) >= 0


def _median(values):
    vals = sorted(values)
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
