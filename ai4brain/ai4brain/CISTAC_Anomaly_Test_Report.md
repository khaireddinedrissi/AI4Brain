# CISTAC anomaly handling — implementation and verification report

**Scope:** six edge cases in `assessment_anomalies.pdf` (3 image-only pages).

## Implemented safeguards

| Assessment case | Detection / handling added | Evidence exposed |
|---|---|---|
| Button Masher | Flags at least 70% of valid observations below 0.8 seconds when current accuracy is 60% or lower; marks the assessment highly uncertain and recommends a contextual check-in rather than interpreting it as an ability drop. | Sample count, median time, fast-response ratio, reason. |
| Stagnation Plateau | Detects a score spread of 2 points or less over the latest four comparable sessions. Fewer than four observations are explicitly insufficient. | Window size and score spread; suggests a task-format/strategy change. |
| “Why” Audit | Coach API can explain a named game/dimension using measured dimension scores; if evidence is missing it says so. | Numeric score vector and whether the selected dimension is the lowest measured dimension. |
| Pushback | Detects explicit disagreement/environmental-distraction statements, rewards challenge/verification signals in collaboration indicators, marks the result uncertain, and invites a retest instead of defending the profile. | Matched user wording and handling response. |
| Fortune Teller Trap | Coach API intercepts exact-future-score requests and refuses certainty; any future projection is described as an estimate requiring a range/confidence interval. | Deterministic guard response. |
| Asymmetrical Mind | Detects a 20-point or greater gap between the strongest and weakest measured dimensions; recommends focus on the weakest and maintenance of the strongest. | Strongest, weakest, gap, and split plan. |

The new `/api/anomalies/evaluate` endpoint accepts an explicit JSON test scenario and returns all six checks. `/api/score` also returns anomaly results; with consent enabled, it uses the user's recent same-task history for response-time and plateau checks. Existing adaptive planning remains the mechanism for per-dimension difficulty and weak/strong allocation.

## Automated verification

`tests/test_anomaly_engine.py`: **8 tests passed** in this environment. Tests cover positive and negative rapid-click cases, plateau and insufficient-history behavior, evidence-linked explanation, pushback, forecast guardrails, asymmetrical planning, and the combined six-check response.

Python syntax compilation is also required for the modified application modules.

## Important limits / pending validation

- The full Flask integration suite and actual browser session were not run here: Flask is not installed in the execution environment, network access prevented installing it, and the archive's bundled virtual environment is Windows-specific.
- The thresholds above are transparent engineering defaults, not empirically calibrated or clinically validated cutoffs. Device latency, accessibility needs, task type, and individual response styles can affect timing.
- Plateau detection is limited to comparable per-task score history and needs at least four stored observations.
- The challenge asks for an unedited screen-recording of the live platform. No authentic live-platform recording is claimed in this report because the server could not be started in this environment. Run the project locally with its documented dependencies and record the live UI/API flow before submission.
