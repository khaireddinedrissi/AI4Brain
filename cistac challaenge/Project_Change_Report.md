# AI4Brain - Project Change Report

**Prepared:** 31 October 2026  
This report summarizes the changes made in this workspace during our conversation. It does not include or reveal the Groq API key.

## Files added

- **`adaptive.py`** — Added the missing bridge between `difficulty_elo.py`, `learning_plan.py`, and SQLite. It loads and updates a separate Elo state per cognitive dimension, maps the 10 Elo levels to the 5 scoring levels, creates weekly plans from configured targets and Brain Twin scores, adds readable skill/game labels for the UI, and can delete adaptive records for an account. With consent, adaptive state and plans are persisted in `data/ai4brain.db`; without consent, state is taken from the browser.
- **`score_config-1.json`** — Aligned the adaptive-learning documentation with the selected `difficulty_elo.py` implementation: 10 Elo levels, initial level 5, K=16, 60% binary success threshold, 1,000-point base rating, and the mapping to five scoring levels.
- **`requirements.txt`** — Added the Python package list for the Flask app: Flask, NumPy, and Groq.
- **`README.md`** — Added Windows PowerShell startup instructions, Python version guidance, dependency installation steps, and coach configuration instructions.
- **`.gitignore`** — Added ignore rules for Streamlit secrets, local databases, user account data, virtual environments, and Python bytecode caches.

## Existing files changed

- **`react.py`** — Signup and login now create or repair a pseudonym-only row in the main SQLite `users` table. Login uses a helper that preserves the user's existing consent choice. Added password-confirmed account deletion and once-daily retention cleanup of expired account and activity data. Account credentials continue to be stored in `users.json`.
- **`database1.py`** — Added `ensure_user_record()`, which inserts a pseudonym row if needed without changing consent fields, plus user deletion and retention-expiry helpers. Related activity rows are removed through SQLite cascade rules.
- **`mod3.py`** — Replaced the old prototype coach entry point with the functions expected by `react.py`: `llm_available()`, `GROQ_MODEL`, and `coach_turn()`. It uses the attached `app (2).py` response pattern: direct answer plus coaching note. The app continues to calculate collaboration scores with `database1.py`'s deterministic logic and uses a local fallback if the LLM is unavailable. Rule-based indicators treat missing evidence as “not observed.”
- **`meesi`** — Updated the coach source to use the attached file's `openai/gpt-oss-20b` model and JSON response structure (`ai_response`, `scores`, `coaching_feedback`). It reads `GROQ_API_KEY` from `.streamlit/secrets.toml` and initializes Groq only when a response is requested. Model score fields are not used as the app's official collaboration score.
- **`index.html`** — Added per-dimension progress lines, a 14-day dimension-by-day heatmap, adjustable targets with progress from each dimension's first recorded score, an automatic Memory Flip sequence hide at higher levels, and a password-confirmed account deletion control. Refreshed chart styling with gradient lines/fills, lighter grids, clearer labels and legends, and hover details. Added day keys and the played dimension to new history records, and excluded the initial unevaluated row from charts. Added Speed Match as a 30-second Processing Speed game, with level-dependent symbol similarity, timed accuracy and response-time scoring, consent-aware database counts, and history/dashboard/export integration. Added a post-round summary for each game with accuracy, response time, and a next-game suggestion based on the current weekly plan. Expanded Pattern Quest to 10 questions in each of its three difficulty bands. Added an interactive Brain Garden to Brain Twin; its four plants grow with dimension-specific practice rounds and reveal the latest score and suggested game. Added browser speech-to-text input and spoken read-aloud controls for Brino; the app receives transcript text, not microphone audio. Added an interactive CSS 3D-style coach persona and user-selected weekly objective, stored in browser progress and supplied to the coach as context.

## Files not changed

`database.py`, `difficulty_elo.py`, `learning_plan.py`, and `database1.sql` were not edited. The existing Elo implementation remains the source of truth; its configuration now documents the same rules.

## Data locations and behavior

- Account credentials and email are kept in `users.json`.
- The main pseudonym and consent row is in `ai4brain.db` in the project folder.
- Adaptive states and saved plans are in `data/ai4brain.db`.
- These are two distinct SQLite databases.
- The app reads `.streamlit/secrets.toml` directly and does not need Streamlit installed. The real secrets file is excluded from Git; `.streamlit/secrets.toml.example` is safe to commit. Python 3.11 or newer is needed for TOML compatibility.

## Validation and limits

A Python syntax compilation check passed for the edited Python modules. A full browser/server run and a live Groq API request were not performed, so those runtime paths still need a local run to confirm in your environment.
