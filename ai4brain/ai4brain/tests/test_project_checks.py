"""Repeatable regression checks for scoring, consent, adaptation, and data lifecycle."""
import json
import math
import re
import sqlite3
import uuid
import unittest
from pathlib import Path
from unittest import mock

import database1
import database
import learning_plan
from difficulty_elo import EloDifficulty

# Give every test disposable database paths so the suite never touches user data.
_workspace = Path(__file__).resolve().parents[1]
import react  # noqa: E402


class ProjectChecks(unittest.TestCase):
    def setUp(self):
        self.test_id = uuid.uuid4().hex
        database1.DB_PATH = _workspace / f".ai4brain-test-{self.test_id}.db"
        database.DB_PATH = _workspace / f".ai4brain-test-adaptive-{self.test_id}.db"
        react.USERS_FILE = _workspace / f".ai4brain-test-users-{self.test_id}.json"
        react._last_retention_cleanup = -math.inf
        react._databases_initialized = False
        database1.init_database()
        database.init_db()
        react._databases_initialized = True
        self.client = react.app.test_client()

    def tearDown(self):
        for path in (database1.DB_PATH, database.DB_PATH, react.USERS_FILE):
            path.unlink(missing_ok=True)

    def post_score(self, **overrides):
        body = {"user_id": "test-user", "name": "Test", "consent": True,
                "game": "Memory Flip", "score": 75, "response_time": 12.0,
                "hesitations": 0, "prev_twin": {}, "prev_elo": {}}
        body.update(overrides)
        return self.client.post("/api/score", json=body)

    def test_score_bounds_and_malformed_inputs_return_400(self):
        for score in (-1, 101, "NaN", "Infinity", None, "not-a-score"):
            with self.subTest(score=score):
                self.assertEqual(self.post_score(score=score).status_code, 400)
        self.assertEqual(self.post_score(response_time=-1).status_code, 400)
        self.assertEqual(self.post_score(response_time="fast").status_code, 400)
        self.assertEqual(self.post_score(hesitations=-1).status_code, 400)
        self.assertEqual(self.post_score(user_id=["bad"]).status_code, 400)
        self.assertEqual(self.post_score(game="unknown").status_code, 400)
        malformed_signup = self.client.post("/api/signup", json={"name": 5, "email": [], "password": 9})
        self.assertEqual(malformed_signup.status_code, 400)

    def test_score_output_stays_in_bounds(self):
        for score in (0, 1, 25, 50, 75, 99, 100):
            with self.subTest(score=score):
                response = self.post_score(score=score)
                self.assertEqual(response.status_code, 200)
                cognitive = response.get_json()["cognitive"]["score"]
                self.assertGreaterEqual(cognitive, 0)
                self.assertLessEqual(cognitive, 100)

    def test_consent_off_computes_but_does_not_persist_game_results(self):
        response = self.post_score(consent=False)
        self.assertEqual(response.status_code, 200)
        with database1.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT consent_given FROM users WHERE user_id='test-user'").fetchone()[0], 0)

    def test_consent_on_persists_session_twin_and_adaptive_state(self):
        response = self.post_score()
        self.assertEqual(response.status_code, 200)
        with database1.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id='test-user'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM brain_twin_history WHERE user_id='test-user'").fetchone()[0], 1)
        react.adaptive._tables()
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM adaptive_states WHERE user_id='test-user'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM adaptive_plans WHERE user_id='test-user'").fetchone()[0], 1)

    def test_missing_dimensions_get_provisional_plan_and_all_elo_dimensions(self):
        response = self.client.post("/api/adaptive", json={"twin": {}, "elo": {}})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(set(payload["levels"]), set(react.adaptive.DIMENSIONS))
        self.assertEqual({row["dimension"] for row in payload["plan"]}, set(react.adaptive.DIMENSIONS))
        self.assertTrue(all(row["role"] == "baseline" for row in payload["plan"]))

    def test_plan_scenarios_allocate_sessions_to_weak_and_maintain_strong(self):
        scenarios = [
            {"WM": 15, "AT": 92, "PS": 55, "SP": 70},
            {"WM": 85, "AT": 20, "PS": 60, "SP": 45},
            {"WM": 45, "AT": 50, "PS": 18, "SP": 95},
            {"WM": 50, "AT": 45, "PS": 80, "SP": 22},
        ]
        importance = {d: 0.25 for d in ("WM", "AT", "PS", "SP")}
        targets = {d: 80 for d in importance}
        difficulty_patterns = [
            {d: 0.1 for d in importance},
            {"WM": 0.9, "AT": 0.1, "PS": 0.5, "SP": 0.9},
            {"WM": 0.2, "AT": 0.8, "PS": 0.1, "SP": 0.6},
        ]
        for scores in scenarios:
            for history_pattern in difficulty_patterns:
                with self.subTest(scores=scores, recent_history=history_pattern):
                    plan = learning_plan.generate_weekly_plan(targets, scores, importance, history_pattern)
                    rows = {r["dimension"]: r for r in plan}
                    weakest = min(scores, key=scores.get)
                    strongest = max(scores, key=scores.get)
                    self.assertEqual(sum(r["sessions"] for r in plan), 7)
                    self.assertGreaterEqual(rows[weakest]["sessions"], 1)
                    self.assertEqual(rows[weakest]["role"], "focus")
                    self.assertGreaterEqual(rows[strongest]["sessions"], 1)
                    self.assertEqual(rows[strongest]["role"], "maintenance")
                    self.assertTrue(all(r["session_minutes"] == 20 for r in plan))

    def test_single_unusual_result_cannot_make_large_elo_jump(self):
        for initial_level in range(1, 11):
            for unusual_score in (0, 100):
                with self.subTest(level=initial_level, score=unusual_score):
                    elo = EloDifficulty(initial_level=initial_level)
                    before_rating, before_level = elo.rating, elo.level
                    elo.update(unusual_score)
                    self.assertLessEqual(abs(elo.rating - before_rating), elo.k_factor)
                    self.assertLessEqual(abs(elo.level - before_level), 1)

    def test_game_level_bands_map_to_visible_exercise_changes(self):
        source = (_workspace / "index.html").read_text(encoding="utf-8")
        expected_fragments = (
            "const memLen=l=>3+Math.round((l-1)*5/9)",
            "const focusCfg=l=>l<=3?{n:8,stars:2}:l<=7?{n:12,stars:3}:{n:16,stars:4}",
            'const pickQs=l=>[...POOLS[l<=3?"easy":l<=7?"mid":"hard"]]',
            "count=l<=3?2:l<=7?3:4",
            "LW>=8?2200:3500",
        )
        for fragment in expected_fragments:
            with self.subTest(mapping=fragment):
                self.assertIn(fragment, source)

    def test_delete_account_removes_credentials_and_saved_data(self):
        signup = self.client.post("/api/signup", json={"name": "Test", "email": "test@example.com", "password": "secret1"})
        self.assertEqual(signup.status_code, 200)
        uid = signup.get_json()["user"]["user_id"]
        self.post_score(user_id=uid, consent=True)
        deletion = self.client.post("/api/delete-account", json={"email": "test@example.com", "password": "secret1"})
        self.assertEqual(deletion.status_code, 200)
        self.assertNotIn("test@example.com", json.loads(react.USERS_FILE.read_text(encoding="utf-8")))
        with database1.get_connection() as conn:
            self.assertIsNone(conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone())
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM adaptive_states WHERE user_id=?", (uid,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM adaptive_plans WHERE user_id=?", (uid,)).fetchone()[0], 0)

    def test_retention_cleanup_removes_expired_account_and_records(self):
        signup = self.client.post("/api/signup", json={"name": "Old", "email": "old@example.com", "password": "secret1"})
        uid = signup.get_json()["user"]["user_id"]
        with database1.get_connection() as conn:
            conn.execute("UPDATE users SET retention_days=1, created_at=datetime('now','-3 days') WHERE user_id=?", (uid,))
        react.adaptive._tables()
        with database.get_connection() as conn:
            conn.execute("INSERT INTO adaptive_states VALUES(?,?,?)", (uid, "WM", json.dumps({"level": 5, "rating": 1400})))
            conn.execute("INSERT INTO adaptive_plans VALUES(?,?,?)", (uid, "2000-01-01", "[]"))
        # Trigger once per test; production throttles this check to once per day.
        react._last_retention_cleanup = -math.inf
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertNotIn("old@example.com", json.loads(react.USERS_FILE.read_text(encoding="utf-8")))
        with database1.get_connection() as conn:
            self.assertIsNone(conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone())
        with database.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM adaptive_states WHERE user_id=?", (uid,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM adaptive_plans WHERE user_id=?", (uid,)).fetchone()[0], 0)

    def test_missing_groq_secret_is_a_clear_service_unavailable_response(self):
        secret_file = _workspace / f".missing-secrets-{self.test_id}.toml"
        with mock.patch.object(react.mod3.meesi, "SECRETS_FILE", secret_file):
            self.assertIsNone(react.mod3.meesi._api_key())
            self.assertFalse(react.mod3.llm_available())
            response = self.client.post("/api/coach", json={"messages": [{"role": "user", "content": "Help"}]})
        self.assertEqual(response.status_code, 503)
        self.assertIn("GROQ_API_KEY", response.get_json()["error"])

    def test_ui_has_labeled_builtin_coach_fallback_for_demo(self):
        source = (_workspace / "index.html").read_text(encoding="utf-8")
        self.assertIn("online?r.reply:ruleReply(p,S,name)", source)
        self.assertIn("Built-in offline guidance", source)
        self.assertIn("Built-in guidance", source)
        self.assertTrue((_workspace / ".streamlit" / "secrets.toml.example").is_file())

    def test_sqlite_outage_returns_controlled_503(self):
        with mock.patch.object(react.db, "get_connection", side_effect=sqlite3.OperationalError("disk unavailable")):
            response = self.post_score()
        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", response.get_json()["error"])

    def test_empty_browser_storage_has_a_default_profile_fallback(self):
        source = (Path(react.BASE_DIR) / "index.html").read_text(encoding="utf-8")
        self.assertTrue(re.search(r"\[user,setUser\]=useState\(null\).{0,200}\[S,setS\]=useState\(INIT\)", source, re.S),
                        "App should initialize from default progress when storage is empty.")
        self.assertTrue("const v=localStorage.getItem(key);if(v)setS(JSON.parse(v))" in source,
                        "Saved progress should override the default when present.")
        self.assertTrue("catch(e){}},[key])" in source,
                        "Invalid or unavailable local storage should not crash the app.")

    def test_primary_ui_and_docs_are_utf8_and_have_no_replacement_glyphs(self):
        for filename in ("index.html", "README.md", "resume.md", "Project_Change_Report.md"):
            with self.subTest(file=filename):
                text = (_workspace / filename).read_text(encoding="utf-8")
                self.assertNotIn("\ufffd", text, f"Replacement character found in {filename}.")
        html = (_workspace / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="en">', html)


if __name__ == "__main__":
    unittest.main()
