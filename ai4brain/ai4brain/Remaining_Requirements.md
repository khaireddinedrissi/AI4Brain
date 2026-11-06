# AI4Brain: Remaining Work for the CISTAC 1.0 Brief

This checklist compares the current project with the challenge requirements supplied in the conversation. It describes work still needed; it does not claim those features are already implemented.

## Priority 1: Complete the core product

### Assessment and cognitive profile

- [x] Add **Speed Match**, a 30-second same/different symbol game, for Processing Speed (SP). Similar symbol pairs increase with the SP Elo level.
- [x] Connect Speed Match accuracy and response time to scoring, Elo difficulty, optional consent-based session storage, Brain Twin history, and the dashboard.
- [ ] Document each live task's definition, instructions, scoring formula, uncertainty, and known biases in the product's technical report. The config describes dimensions, but its task labels do not always match the actual game implementations.
- [ ] Keep the UI clear that all scores are practice indicators, not clinical assessments.

### Brain Twin and history

- [ ] Show uncertainty beside each dimension score and keep the confidence range visible or accessible in the dashboard.
- [ ] Ensure the user can see a longitudinal score history for each dimension, not only a single overall curve.
- [ ] If future projections are included, generate and display each projection with its uncertainty and label it as an estimate. Otherwise, leave projections out of the demo and claims; they are optional.

### Adaptive learning and weekly plan

- [x] Select `difficulty_elo.py` as the difficulty rule set and align the config: 10 Elo levels, K=16, success at 60%, and a mapping to the five scoring levels.
- [x] Fix the weekly-plan display. Generated rows now include readable skill and game names, including when loading an older saved plan.
- [x] Make each recommendation actionable: show the target dimension, current score (or explicitly provisional estimate), target, gap, sessions, session duration, and the game to play.
- [x] Allocate weighted practice toward the lowest measured score and reserve at least one weekly session to maintain a different, stronger measured skill.
- [x] Refresh the plan after each result and show a notice explaining a changed weekly focus or the updated score gap.

### Dashboard

- [x] Add **progress curves per active dimension** (working memory, attention, problem solving, and processing speed). The overall curve remains available. Speed Match results now appear as the fourth dimension.
- [x] Add a **dimension-by-day heatmap** for the latest 14 days using recorded score snapshots; days with no sessions have a distinct empty cell.
- [x] Add **goal tracking** with editable per-dimension targets, first recorded score, current score, and bounded progress toward the target.
- [ ] Show the weekly plan on the dashboard with readable game names and details.
- [ ] Keep the radar chart readable when a dimension has no data; mark it as unevaluated instead of implying a zero ability score.

### AI coach and AI Collaboration Score

- [ ] Make coach replies consistently explain the reason for a recommendation and provide two practical next steps, as required by the project config.
- [ ] Keep the coach grounded in recorded scores, uncertainty, recent performance, and the current plan. It should say when there is not enough information.
- [ ] Preserve the deterministic app-side AI Collaboration Score calculation. Do not present LLM-generated score fields as authoritative.
- [ ] Improve and validate the current phrase-matching behavior indicators. Store evidence for observed behaviors, leave unobserved items unevaluated, and avoid claiming the score is validated until it has been evaluated.
- [ ] Check every coach response against the configured forbidden-term list before display or storage; return a safe fallback if it fails.

## Priority 2: Finish privacy and data controls

- [x] Add a **delete my data/account** action with password confirmation. It removes the login record, the main SQLite user row and its cascading activity data, adaptive states/plans, and browser-local progress.
- [x] Add server-side retention cleanup using each user's configured retention period. Cleanup runs at most once per day when the app receives a request and removes expired login records and data from both SQLite databases.
- [ ] Document exactly what is stored with consent off versus consent on, including browser local storage, pseudonym, game data, coach interaction indicators, and email reminders.
- [ ] Provide a way to withdraw consent and explain what is deleted and what remains.
- [ ] Keep camera and voice out of scope unless implemented with explicit opt-in and safeguards. The non-biometric flow is already the appropriate default.

## Priority 3: Validate quality and robustness

- [x] Add repeatable checks for score bounds, malformed API input, missing dimensions, consent behavior, persistence, plan allocations, and deletion/retention behavior. See `tests/test_project_checks.py` and `Quality_Checks_and_Evaluation.md`.
- [x] Evaluate the games and plans across varied starting profiles and score histories; record how generalizable the outputs are and their limitations. The evaluation covers hand-selected scenarios and documents that these are not participant-study results.
- [x] Test graceful behavior when Groq is unavailable, secrets are missing, SQLite is unavailable, or the browser has no stored state. Without a key, the coach falls back to labeled rule-based guidance. The no-browser-storage check is source-level; see the report for browser validation still needed.
- [x] Confirm the adaptive difficulty changes the exercise in an understandable way and does not make a single unusual score cause a large jump. Tests cover the Elo update bound; game level mappings are documented in the evaluation report.
- [x] Check the primary UI and official user-facing documents for UTF-8 decoding/replacement characters and keep their primary language English. Bilingual coach responses remain available.

## Priority 4: Prepare the submission package

- [ ] Prepare a public GitHub repository. Do not include `.streamlit/secrets.toml`, `users.json`, SQLite databases, or other private user data. Include `.streamlit/secrets.toml.example` only.
- [ ] Write the challenge **technical report** within the eight-page limit. The existing `Project_Change_Report.md` documents code changes; it is not this technical report.
- [ ] Prepare a presentation of no more than 15 slides.
- [ ] Record a 3–5 minute demo video showing signup/consent, games, adaptive changes, Brain Twin/dashboard, the weekly plan, and the coach.
- [ ] Rehearse the eight-minute pitch and five-minute Q&A format for Phase 2.
- [ ] Include measured results and honest limitations for profile quality, plan relevance, robustness, and generalisation; avoid unsupported claims.

## Suggested order

1. Exercise the new SP game through a browser run and confirm its saved and unsaved consent paths.
2. Validate scoring, adaptation, consent, privacy, and coach behavior. Repeatable automated checks now live in `tests/`; a manual browser pass and live-provider checks remain.
3. Produce the technical report, slides, demo video, and public repository.

## Important existing limitations

- Browser-run validation is still needed for all four game flows, including Speed Match.
- The plan table now receives its skill and game labels from the adaptive bridge.
- The dashboard now has per-dimension curves, a recent day-by-dimension heatmap, and target tracking for all four active dimensions, including Speed Match results for Processing Speed.
- Account deletion and daily retention cleanup are implemented across account JSON, both SQLite databases, and local browser progress.
- The challenge asks for evaluation of generalisation and robustness; source code alone does not demonstrate those results.


## CISTAC anomaly scenarios (assessment_anomalies.pdf)

- [x] Add explicit, evidence-returning detection and handling for all six listed challenge cases in `anomaly_engine.py`.
- [x] Return anomaly assessments from `/api/score` and provide `/api/anomalies/evaluate` for deterministic QA scenarios.
- [x] Add coach guardrails for exact future-score predictions, evidence-based “why” responses, and respectful user pushback.
- [x] Add focused unit tests for all six scenarios (`tests/test_anomaly_engine.py`).
- [ ] Run the complete Flask integration suite and a real browser session on the target Windows environment.
- [ ] Capture the requested short, unedited screen recording from the running platform. This workspace could not start Flask because its runtime dependencies were unavailable.
