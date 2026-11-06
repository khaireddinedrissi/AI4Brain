"""Bridge Elo difficulty, weekly plans, and SQLite persistence."""
from datetime import date
import json

from difficulty_elo import EloDifficulty
from learning_plan import generate_weekly_plan
import database1 as cognitive_db
import database

DIMENSIONS = ("WM", "AT", "PS", "SP")
DEFAULT_LEVEL = 5


def _tables():
    database.init_db()
    with database.get_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS adaptive_states (user_id TEXT NOT NULL, dimension TEXT NOT NULL, state_json TEXT NOT NULL, PRIMARY KEY(user_id, dimension))")
        conn.execute("CREATE TABLE IF NOT EXISTS adaptive_plans (user_id TEXT PRIMARY KEY, week_start TEXT NOT NULL, plan_json TEXT NOT NULL)")


def _clean_state(value):
    value = value if isinstance(value, dict) else {}
    try:
        level = max(1, min(10, int(value.get("level", DEFAULT_LEVEL))))
        rating = float(value.get("rating", 1000 + (level - 1) * 100))
    except (TypeError, ValueError):
        level, rating = DEFAULT_LEVEL, 1400.0
    return {"level": level, "rating": rating, "history": value.get("history", [])[-5:]}


def load_states(user_id=None, consent=False, client_states=None):
    if user_id and consent:
        _tables()
        with database.get_connection() as conn:
            rows = conn.execute("SELECT dimension,state_json FROM adaptive_states WHERE user_id=?", (user_id,)).fetchall()
        saved = {d: json.loads(s) for d, s in rows}
        source = {**(client_states or {}), **saved}
    else:
        source = client_states if isinstance(client_states, dict) else {}
    return {d: _clean_state(source.get(d)) for d in DIMENSIONS}


def scoring_level(elo_level):
    return max(1, min(5, (int(elo_level) + 1) // 2))


def levels_view(states):
    return {d: int(states[d]["level"]) for d in DIMENSIONS}


def _add_plan_labels(plan):
    labels = {"WM": ("Working Memory", "Memory Flip"),
              "AT": ("Attention", "Focus Sprint"),
              "PS": ("Problem Solving", "Pattern Quest"),
              "SP": ("Processing Speed", "Speed Match")}
    for row in plan:
        row["name"], row["game"] = labels.get(row["dimension"], (row["dimension"], "Practice"))
    return plan


def apply_result(user_id, consent, dimension, score, response_time=None, states=None):
    if dimension not in DIMENSIONS:
        raise ValueError("Unknown cognitive dimension")
    states = states or load_states(user_id, consent)
    state = _clean_state(states.get(dimension))
    elo = EloDifficulty(initial_level=state["level"])
    elo.rating = state["rating"]
    result = elo.update(float(score))
    state.update(level=elo.level, rating=elo.rating)
    state["history"] = (state.get("history", []) + [{"score": float(score), "level": elo.level}])[-5:]
    states[dimension] = state
    if user_id and consent:
        _tables()
        with database.get_connection() as conn:
            conn.execute("INSERT INTO adaptive_states VALUES(?,?,?) ON CONFLICT(user_id,dimension) DO UPDATE SET state_json=excluded.state_json", (user_id, dimension, json.dumps(state)))
    return result


def _plan(user_id, consent, twin, states):
    cfg = cognitive_db._config()["adaptive_bridge"]["weekly_plan"]
    dims = list(cfg["importance"])
    current, difficulty, unevaluated = {}, {}, []
    dims_data = (twin or {}).get("dimensions", twin or {})
    for d in dims:
        entry = dims_data.get(d) or {}
        if isinstance(entry, dict) and entry.get("score") is not None:
            current[d] = float(entry["score"])
        else:
            current[d] = float(cfg["provisional_score"])
            unevaluated.append(d)
        hist = states.get(d, {}).get("history", [])
        difficulty[d] = (sum(max(1, min(10, int(x.get("level", states[d]["level"])))) for x in hist) / len(hist) / 10) if hist else states[d]["level"] / 10
    objectives = {d: cfg["target_score"] for d in dims}
    plan = generate_weekly_plan(objectives, current, cfg["importance"], difficulty,
                                cfg["total_sessions"], cfg["session_minutes"], unevaluated)
    _add_plan_labels(plan)
    if user_id and consent:
        _tables()
        with database.get_connection() as conn:
            conn.execute("INSERT INTO adaptive_plans VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET week_start=excluded.week_start,plan_json=excluded.plan_json", (user_id, date.today().isoformat(), json.dumps(plan, ensure_ascii=False)))
    return plan


def refresh_plan(user_id, consent, twin, states):
    return _plan(user_id, consent, twin, states)


def current_plan(user_id, consent, twin, states):
    if user_id and consent:
        _tables()
        with database.get_connection() as conn:
            row = conn.execute("SELECT week_start,plan_json FROM adaptive_plans WHERE user_id=?", (user_id,)).fetchone()
        if row and row[0] == date.today().isoformat():
            cached = json.loads(row[1])
            if all("role" in item and "evaluated" in item for item in cached):
                return _add_plan_labels(cached)
    return _plan(user_id, consent, twin, states)


def delete_users(user_ids):
    """Remove adaptive state and plans for the supplied user IDs."""
    ids = list(set(user_ids or []))
    if not ids:
        return
    _tables()
    placeholders = ",".join("?" for _ in ids)
    with database.get_connection() as conn:
        conn.execute(f"DELETE FROM adaptive_states WHERE user_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM adaptive_plans WHERE user_id IN ({placeholders})", ids)
