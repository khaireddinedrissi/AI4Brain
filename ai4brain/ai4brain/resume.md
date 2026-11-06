# AI4Brain Project Work Summary

**Updated:** 1 November 2026

## Project

AI4Brain is a Flask-based cognitive growth prototype with a browser UI. It includes four practice games, cognitive score tracking, an adaptive difficulty layer, weekly plans, and an optional Groq-powered coach.

## Work completed in this workspace

- Added `adaptive.py` to connect the existing Elo difficulty logic, weekly plan generator, and SQLite storage. Difficulty state is tracked separately for working memory, attention, problem solving, and processing speed. Elo levels map to the five scoring-weight levels.
- Confirmed `difficulty_elo.py` as the source of truth and aligned `score_config-1.json` with its 10-level, K=16, 60%-success rules.
- Added persistence for adaptive state and weekly plans when consent is enabled; without consent, the adaptive state is passed through browser state.
- Added readable skill and game labels to generated and previously saved weekly plans so the existing plan table can display them.
- Added password-confirmed account deletion across `users.json`, the main SQLite database, adaptive SQLite state, and browser-local progress. Added daily retention cleanup for expired accounts and data.
- Adapted the coach to the supplied `app (2).py` response pattern: Groq's `openai/gpt-oss-20b` returns a direct answer and a separate coaching note. The key is read from `.streamlit/secrets.toml`; official collaboration scoring remains calculated by the app's deterministic code.
- Added a pseudonym-only database row when users sign up or sign in. The helper in `database1.py` preserves the user's existing consent setting. Login credentials remain in `users.json`.
- Added `requirements.txt`, Windows setup instructions in `README.md`, and `.gitignore` rules for secrets and local data files.
- Created `Project_Change_Report.md` and `Project_Change_Report.pdf` to document the code changes.
- Created `Remaining_Requirements.md` to map gaps against the CISTAC 1.0 challenge brief.
- Ran a Python syntax compilation check on the edited Python modules; it passed. A complete browser/server run and live Groq request have not been confirmed.

## Current capabilities reviewed

- Four playable games: Memory Flip, Focus Sprint, Pattern Quest, and Speed Match (30-second processing-speed rounds). Each completed round now shows accuracy, response time, and the next game suggested by the weekly plan. Pattern Quest has 30 questions across its three difficulty bands (10 per band). Brino supports browser speech input and read-aloud replies; only transcript text reaches the app. The interactive 3D-style Brino avatar reacts while thinking or speaking, and users can set a weekly coaching objective.
- Cognitive scores use accuracy, response time, and hesitation data, with Brain Twin score history and uncertainty support.
- Elo difficulty adapts across the four active dimensions.
- The dashboard includes a Brain Garden that grows with practice rounds, a radar chart, an overall curve, per-dimension curves, a 14-day day-by-dimension heatmap, editable score goals, and session history.
- Memory Flip now hides the digit sequence automatically from level 6 onward, with a shorter viewing time at levels 8–10.
- The coach can provide personalized text through Groq when configured, with a local fallback when unavailable.
- Consent controls govern saving game results and collaboration data.

## Main remaining work

- Validate the new Speed Match game and its Processing Speed scoring/adaptation in a browser session.
- Validate scoring, adaptation, coach behavior, consent handling, privacy, robustness, and generalisation.
- Prepare the challenge technical report (maximum eight pages), presentation (maximum 15 slides), 3–5 minute demo video, and public GitHub repository.

See [Remaining_Requirements.md](Remaining_Requirements.md) for the detailed checklist and [Project_Change_Report.md](Project_Change_Report.md) for the file-by-file change history.
