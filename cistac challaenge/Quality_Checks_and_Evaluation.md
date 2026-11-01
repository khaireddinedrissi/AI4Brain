# Quality Checks and Scenario Evaluation

## What these checklist items mean

- **Repeatable checks:** small automated checks that can be rerun after code changes. They catch regressions in score bounds, request validation, consent, saved data, plan math, and deletion/retention.
- **Different profiles and histories:** try the same plan rules with users who have different low and high dimensions, plus different recent difficulty levels. This checks whether a rule behaves consistently across representative cases.
- **Graceful failure:** show a clear response when an optional service or database is unavailable, instead of crashing or returning an unexplained server error.
- **Understandable adaptation:** check that the difficulty step changes visible game parameters and that one unusual result cannot cause a large rating jump.
- **Encoding and language:** ensure the HTML and user-facing documents decode as UTF-8 and the primary interface/submission text is English.

These checks verify implementation behavior. They do not establish that the scores measure cognitive ability or that the plans improve real-world outcomes.

## Run the checks

From the project folder, with the dependencies installed:

```powershell
py -m unittest discover -s tests -v
```

The suite uses temporary, uniquely named SQLite files in the project folder and removes them after each test. It does not use real accounts or saved user records.

## Coverage and result

The current suite has 15 automated tests. It checks:

| Area | Check performed |
| --- | --- |
| Score/API validation | Scores below 0, above 100, non-numbers, NaN/infinity, invalid game/user IDs, negative or malformed timing/hesitations, and malformed signup data are rejected. Valid boundary/intermediate scores return cognitive scores in the 0–100 range. |
| Missing dimensions | An empty Brain Twin and Elo payload return all four dimensions, marked as provisional baseline plan rows. |
| Consent and persistence | With consent off, the game response is still calculated but no game session is saved. With consent on, the session, Brain Twin history, adaptive state, and plan are saved. |
| Plan allocations | Four profiles (one weakest dimension per dimension) are combined with three recent-difficulty patterns. Every plan allocates seven sessions, gives the weakest measured area at least one focus session, and preserves at least one session for a different strongest area. |
| Elo outliers | For every starting level 1–10, both 0% and 100% outcomes are checked. A single update changes rating by no more than K=16 and level by no more than one step. |
| Game difficulty mappings | Static regression checks pin the visible level bands for all four games: memory length/hide timing, focus board/targets, pattern bank, and speed symbol count. |
| Deletion and retention | Password-confirmed deletion removes credentials and SQLite/adaptive records. A user past the configured retention period is removed from the account file and database. |
| Missing service/storage | A missing Groq secret returns HTTP 503 from the coach API and the UI uses clearly labeled built-in rule guidance. A simulated SQLite outage returns a controlled HTTP 503. |
| Empty browser state and encoding | The UI has a default profile when local storage is empty/unreadable; primary HTML and docs are checked for UTF-8 decoding and replacement characters. |

The suite passed locally on 1 November 2026: **15 tests passed**. It includes 12 profile/history plan combinations and 20 extreme-score Elo cases.

## Difficulty is visible in the games

The game UI maps Elo level to understandable exercise changes:

| Game | Visible progression |
| --- | --- |
| Memory Flip | Sequence grows from 3 to 8 digits; from level 6, it hides automatically after a short display, with a shorter display at levels 8–10. |
| Focus Sprint | Board grows from 8 to 12 to 16 symbols, with 2, 3, then 4 target stars across levels 1–3, 4–7, and 8–10. |
| Pattern Quest | The selected question bank moves from easy to medium to hard across those same level bands. |
| Speed Match | The number of symbols increases from 2 to 3 to 4; harder levels use more similar symbol pairs. |

One unusual score does not jump the Elo rating by more than 16 points because the configured K-factor is 16. The game difficulty level changes in whole steps and is bounded to 1–10. This limits abrupt changes; it does not prove the chosen K-factor is optimal for learners.

## Scenario evaluation and limitations

The scenario matrix deliberately rotates the weakest skill through working memory, attention, problem solving, and processing speed. It also varies recent difficulty from low to mixed/high. In all tested combinations, the weakest skill receives a focus session and a distinct strongest skill receives maintenance. Empty profiles produce baseline recommendations instead of being treated as measured ability.

This is **rule coverage**, not a participant study. The scenarios are hand-selected examples, not a representative sample of people. They do not establish fairness across age, language, disability, device, education, or culture. The game exercises are short prototypes; repeated play, practice effects, random question selection, response devices, and the fixed score formula may affect results. Do not present the profile as a clinical or validated cognitive assessment.

The empty-browser check is a source-level regression check, not a full browser automation run. A manual browser pass is still needed for signup/guest start, all four games at low and high levels, consent on/off, local storage disabled, mobile layout, and visual legibility. Groq API behavior is not tested against the live provider; missing-key behavior is tested locally.

## Graceful failure behavior

- The static home page does not need SQLite to load. Storage initializes on the first API request; API requests return a safe HTTP 503 response if SQLite is unavailable.
- Without `GROQ_API_KEY`, the app and games remain available. The coach endpoint reports that the optional coach service is unavailable, and the browser uses its labeled built-in guidance fallback.
- In the browser, a failed or unavailable coach request falls back to labeled rule-based guidance, so the demo coach remains usable without a private key. This fallback is not a generative LLM response.
- When browser local storage is empty or throws an access/parse error, the app starts from its built-in default profile. Progress cannot persist in that browser until storage becomes available.

