"""Pont entre l'interface React (index.html) et la plateforme Python.

Modules utilisés (chacun garde sa logique d'origine) :
  database1.py   score cognitif, Brain Twin, point faible, engagement/moral, AI Collaboration Score
                 (formules : score_config-1.json, schéma : database1.sql)
  adaptive.py    relie difficulty_elo.py (Elo), learning_plan.py (plan hebdo) et database.py (stockage)
  mod3.py        coach IA « Brino » : Groq uniquement

Lancer :  pip install -r requirements.txt
          export GROQ_API_KEY=...   (PowerShell : $env:GROQ_API_KEY="...")
          python react.py  ->  http://localhost:5000
"""
import edge_tts
import io
import asyncio
import hashlib, hmac, json, math, os, re, secrets, sqlite3, threading, time, traceback
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, Response
import database1 as db
import database as store
import adaptive
import anomaly_engine
import mod3

BASE_DIR = Path(__file__).resolve().parent
# static_folder=None : ne JAMAIS exposer le dossier du projet (users.json, ai4brain.db, code source...)
app = Flask(__name__, static_folder=None)
USERS_FILE = BASE_DIR / "users.json"
GAMES = ("Memory Flip", "Focus Sprint", "Pattern Quest", "Speed Match")
_RETENTION_INTERVAL = 24 * 60 * 60
_retention_lock = threading.Lock()
_last_retention_cleanup = 0.0
_database_init_lock = threading.Lock()
_databases_initialized = False


def initialize_databases():
    """Initialize storage on demand so the static app can still load offline."""
    global _databases_initialized
    if _databases_initialized:
        return
    with _database_init_lock:
        if not _databases_initialized:
            db.init_database()
            store.init_db()
            _databases_initialized = True


@app.errorhandler(sqlite3.Error)
def handle_storage_error(error):
    """Return a controlled API response when SQLite is unavailable."""
    traceback.print_exc()
    if request.path.startswith("/api/"):
        return jsonify(ok=False, error="Saved data is temporarily unavailable. Please try again."), 503
    return "Saved data is temporarily unavailable. Please try again.", 503


def body():
    d = request.get_json(force=True, silent=True)
    return d if isinstance(d, dict) else {}


def load_users():
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_users(users):
    temp_file = USERS_FILE.with_name(USERS_FILE.name + ".tmp")
    temp_file.write_text(json.dumps(users, indent=2), encoding="utf-8")
    os.replace(temp_file, USERS_FILE)


def cleanup_expired_accounts():
    """Run retention cleanup at most once per day, removing data and login records."""
    global _last_retention_cleanup
    now = time.monotonic()
    if now - _last_retention_cleanup < _RETENTION_INTERVAL:
        return
    with _retention_lock:
        now = time.monotonic()
        if now - _last_retention_cleanup < _RETENTION_INTERVAL:
            return
        expired_ids = db.expired_user_ids()
        if expired_ids:
            expired_ids = set(expired_ids)
            users = load_users()
            kept = {email: account for email, account in users.items()
                    if user_id_for(email) not in expired_ids}
            if len(kept) != len(users):
                save_users(kept)
            adaptive.delete_users(expired_ids)
            db.delete_users(expired_ids)
        _last_retention_cleanup = now


def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 150_000).hex()


def user_id_for(email):  # identique à init_state() de app2.py
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def merged_twin(uid, consent, client_twin):
    """Brain Twin envoyé par le navigateur, complété par la base (qui fait foi) si l'utilisateur a consenti."""
    twin = dict(client_twin or {})
    if uid and consent:
        twin.update(db.get_brain_twin(uid))
    return twin


@app.before_request
def run_retention_cleanup():
    if not request.path.startswith("/api/"):
        return
    try:
        initialize_databases()
        cleanup_expired_accounts()
    except sqlite3.Error:
        return jsonify(ok=False, error="Saved data is temporarily unavailable. Please try again."), 503
    except Exception:
        traceback.print_exc()


@app.get("/api/health")
def health():
    """Vérification rapide : le LLM Groq est-il configuré ?"""
    return jsonify(ok=True, llm=mod3.llm_available(), model=mod3.GROQ_MODEL,
                   message=("Groq is ready" if mod3.llm_available() else "GROQ_API_KEY is not configured"))


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.post("/api/signup")
def signup():
    d = body()
    name, key, pw = d.get("name"), d.get("email"), d.get("password")
    if (not isinstance(name, str) or not isinstance(key, str) or not isinstance(pw, str) or
            not name.strip() or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", key.strip().lower()) or len(pw) < 6):
        return jsonify(ok=False, error="Invalid data."), 400
    name, key = name.strip(), key.strip().lower()
    users = load_users()
    if key in users:
        return jsonify(ok=False, error="An account with this email already exists. Sign in instead.")
    salt = secrets.token_hex(16)
    users[key] = {"name": name, "salt": salt, "hash": hash_pw(pw, salt), "created": datetime.now().strftime("%Y-%m-%d")}
    try:
        save_users(users)
    except Exception:
        return jsonify(ok=False, error="Could not save the account (read-only folder).")
    uid = user_id_for(key)
    # Keep the pseudonym-only app database in sync; credentials remain in users.json.
    db.ensure_user_record(user_id=uid, pseudonym=name)
    return jsonify(ok=True, user={"email": key, "name": name, "user_id": uid})


@app.post("/api/login")
def login():
    d = body()
    raw_key, password = d.get("email"), d.get("password")
    if not isinstance(raw_key, str) or not isinstance(password, str):
        return jsonify(ok=False, error="Email or password is incorrect."), 400
    key = raw_key.strip().lower()
    u = load_users().get(key)
    if u and hmac.compare_digest(u["hash"], hash_pw(password, u["salt"])):
        uid = user_id_for(key)
        # Also populate the database for accounts created before this sync was added.
        db.ensure_user_record(user_id=uid, pseudonym=u["name"])
        return jsonify(ok=True, user={"email": key, "name": u["name"], "user_id": uid,
                                      "email_consent": db.get_email_consent(uid)})
    return jsonify(ok=False, error="Email or password is incorrect.")


@app.post("/api/delete-account")
def delete_account():
    """Require the account password, then delete the account and its stored data."""
    d = body()
    email = d.get("email")
    password = d.get("password")
    if not isinstance(email, str):
        return jsonify(ok=False, error="Email or password is incorrect."), 401
    email = email.strip().lower()
    account = load_users().get(email)
    if (not account or not isinstance(password, str) or
            not hmac.compare_digest(account["hash"], hash_pw(password, account["salt"]))):
        return jsonify(ok=False, error="Email or password is incorrect."), 401

    users = load_users()
    users.pop(email, None)
    try:
        save_users(users)
        uid = user_id_for(email)
        adaptive.delete_users([uid])
        db.delete_user_data(uid)  # Related activity rows are removed by SQLite cascades.
    except Exception:
        traceback.print_exc()
        # Restore the login record if persistence failed so the user can retry.
        users[email] = account
        try:
            save_users(users)
        except OSError:
            traceback.print_exc()
        return jsonify(ok=False, error="Could not complete account deletion. Please try again."), 500
    return jsonify(ok=True)


@app.post("/api/start")
def start():
    """Une partie commence : sert à détecter les abandons (signal Q)."""
    d = body()
    if not isinstance(d.get("user_id"), str) or not d["user_id"].strip() or len(d["user_id"]) > 128 or d.get("game") not in GAMES:
        return jsonify(ok=False, error="Invalid data."), 400
    consent = bool(d.get("consent"))
    db.ensure_user(user_id=d["user_id"], pseudonym=d.get("name", ""), consent=consent)
    if consent:
        db.log_game_event(d["user_id"], d["game"], "started")
    return jsonify(ok=True)


@app.post("/api/score")
def score():
    """`score` envoyé par le navigateur = précision brute du jeu (0-100).
    Tout le reste est calculé ici : score cognitif et Brain Twin (database1.py / score_config-1.json),
    niveau de difficulté Elo (difficulty_elo.py) et plan hebdomadaire (learning_plan.py)."""
    d = body()
    if not isinstance(d.get("user_id"), str) or not d["user_id"].strip() or len(d["user_id"]) > 128 or d.get("game") not in GAMES:
        return jsonify(ok=False, error="Invalid game data."), 400
    try:
        raw_score = float(d["score"])
        if not math.isfinite(raw_score) or not 0 <= raw_score <= 100:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        return jsonify(ok=False, error="The raw score must be between 0 and 100."), 400
    try:
        response_time = d.get("response_time")
        if response_time is not None:
            response_time = float(response_time)
            if not math.isfinite(response_time) or not 0 <= response_time <= 86400:
                raise ValueError
        hesitations = int(d.get("hesitations", 0))
        if hesitations < 0 or hesitations > 10000:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return jsonify(ok=False, error="Invalid response time or hesitation count."), 400
    correct_count = total_count = None
    if d.get("game") == "Speed Match":
        try:
            correct_count, total_count = int(d["correct_count"]), int(d["total_count"])
            if not 1 <= total_count <= 300 or not 0 <= correct_count <= total_count:
                raise ValueError
            expected_accuracy = round(100 * correct_count / total_count)
            if abs(expected_accuracy - raw_score) > 1:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
            return jsonify(ok=False, error="Invalid Speed Match result."), 400
    uid, game, consent = d["user_id"], d["game"], bool(d.get("consent"))
    db.ensure_user(user_id=uid, pseudonym=d.get("name", ""), consent=consent)

    dim = db._config()["cognitive_scoring"]["game_to_dimension"][game]
    # Niveau de difficulté auquel la partie a été jouée (base si consentement, sinon état du navigateur)
    states = adaptive.load_states(uid, consent, d.get("prev_elo"))
    level = adaptive.scoring_level(states[dim]["level"])        # 10 niveaux Elo -> poids difficulty_weight (1..5)
    ev = db.evaluate_attempt(game, raw_score, response_time, hesitations, level=level)
    client_twin = d.get("prev_twin") or {}          # état du Brain Twin gardé dans le navigateur
    engagement, twin = None, dict(client_twin)

    if consent:  # on n'enregistre que si l'utilisateur a accepté
        sid = db.save_game_session(
            user_id=uid, game=game, score=raw_score,
            response_time=response_time, hesitation_count=hesitations, level=level,
            correct_count=correct_count, total_count=total_count)
        db.update_brain_twin(uid, sid, dim, ev["score"], prev_override=client_twin.get(dim))
        twin.update(db.get_brain_twin(uid))          # la base fait foi pour les dimensions enregistrées
        try:
            engagement = db.compute_engagement_state(uid, sid)
        except Exception:
            traceback.print_exc()
            engagement = None  # l'engagement ne doit jamais bloquer l'enregistrement du score
    else:
        twin[dim] = db.twin_step(client_twin.get(dim), ev["score"])   # même formule, sans rien stocker

    adaptive_out = None
    try:
        res = adaptive.apply_result(uid, consent, dim, ev["score"], response_time, states)
        plan = adaptive.refresh_plan(uid, consent, twin, states)
        adaptive_out = {"result": res, "levels": adaptive.levels_view(states), "elo": states, "plan": plan}
    except Exception:
        traceback.print_exc()                        # l'adaptation ne doit pas faire perdre le score déjà enregistré

    anomaly_history = {"response_times": [], "score_history": []}
    if consent:
        task_names = {"Memory Flip": "reverse_digit_span", "Focus Sprint": "target_detection",
                      "Pattern Quest": "number_sequence", "Speed Match": "symbol_matching"}
        with db.get_connection() as conn:
            rows = conn.execute(
                """SELECT a.response_time, a.score FROM task_attempts a
                   JOIN sessions s ON s.id = a.session_id
                   JOIN cognitive_tasks t ON t.id = a.task_id
                   WHERE s.user_id = ? AND t.task_name = ? AND s.session_type = 'game'
                   ORDER BY s.id DESC LIMIT 5""", (uid, task_names[game])).fetchall()
        anomaly_history["response_times"] = [r[0] for r in reversed(rows) if r[0] is not None]
        anomaly_history["score_history"] = [r[1] for r in reversed(rows) if r[1] is not None]
    anomaly_payload = {
        "response_times": d.get("response_times") or (anomaly_history["response_times"] + ([response_time] if response_time is not None else [])),
        "accuracy": raw_score,
        "score_history": d.get("score_history") or (anomaly_history["score_history"] + [ev["score"]]),
        "dimension_scores": {k: (v or {}).get("score") for k, v in twin.items()
                             if k in anomaly_engine.DIMENSIONS and isinstance(v, dict)},
        "recommended_dimension": min(
            ((v or {}).get("score"), k) for k, v in twin.items()
            if k in anomaly_engine.DIMENSIONS and isinstance(v, dict)
            and isinstance((v or {}).get("score"), (int, float))
        )[1] if any(k in anomaly_engine.DIMENSIONS and isinstance(v, dict)
                    and isinstance((v or {}).get("score"), (int, float)) for k, v in twin.items()) else None
    }
    anomaly_report = anomaly_engine.analyze(anomaly_payload)
    return jsonify(ok=True, cognitive=ev, twin=db.twin_view(twin), engagement=engagement,
                   adaptive=adaptive_out, anomalies=anomaly_report)


@app.post("/api/adaptive")
def adaptive_state():
    """Niveaux Elo + plan hebdomadaire courants (base si consentement, sinon état du navigateur)."""
    d = body()
    uid, consent = d.get("user_id") or None, bool(d.get("consent"))
    twin = merged_twin(uid, consent, d.get("twin"))
    states = adaptive.load_states(uid, consent, d.get("elo"))
    return jsonify(ok=True, levels=adaptive.levels_view(states), elo=states,
                   plan=adaptive.current_plan(uid, consent, twin, states),
                   twin=db.get_brain_twin(uid) if (uid and consent) else {})


@app.get("/api/twin")
def twin_latest():
    return jsonify(ok=True, twin=db.twin_view(db.get_brain_twin(request.args.get("user_id", ""))))


@app.post("/api/coach")
def coach():
    """Coach IA : calculs par database1 / adaptive (scores, point faible, plan, AI Collaboration Score), texte par Groq."""
    d = body()
    chat = [{"role": "assistant" if m.get("role") == "assistant" else "user", "content": str(m.get("content", ""))[:2000]}
            for m in (d.get("messages") or []) if isinstance(m, dict)][-20:]
    if not chat or chat[-1]["role"] != "user":
        return jsonify(ok=False, error="There is no user message to process."), 400
    latest_user_message = chat[-1]["content"]
    forecast_guard = anomaly_engine.guard_prediction(latest_user_message)
    pushback = anomaly_engine.detect_pushback(latest_user_message)
    if forecast_guard["guarded"]:
        return jsonify(ok=True, reply=forecast_guard["response"], answer=forecast_guard["response"],
                       collab={"source": "rules", "saved": False}, chat_sid=d.get("chat_sid"),
                       weakest=None, safeguards={"fortune_teller": forecast_guard, "pushback": pushback})
    is_why_audit = any(term in latest_user_message.lower() for term in
                       ("why did you assign", "why this exercise", "why this game", "why this task"))
    if not mod3.llm_available() and not (pushback["detected"] or is_why_audit):
        return jsonify(ok=False, error="GROQ_API_KEY is missing. Configure it before starting the coach."), 503
    uid, consent = d.get("user_id"), bool(d.get("consent"))
    if uid:
        db.ensure_user(user_id=uid, pseudonym=d.get("name", ""), consent=consent)
    try:
        out = mod3.coach_turn(uid, d.get("name", ""), consent, chat, twin=d.get("twin"),
                              chat_sid=d.get("chat_sid"), elo=d.get("elo"), objective=d.get("objective"))
    except Exception as e:
        traceback.print_exc()                      # détail complet dans le terminal
        return jsonify(ok=False, error=f"{type(e).__name__}: {e}"), 500
    answer = out["answer"]
    twin_for_audit = d.get("twin") or {}
    dims_for_audit = twin_for_audit.get("dimensions", twin_for_audit)
    measured_scores = {k: (v or {}).get("score") for k, v in dims_for_audit.items()
                       if k in anomaly_engine.DIMENSIONS and isinstance(v, dict)
                       and isinstance((v or {}).get("score"), (int, float))}
    why_audit = None
    if any(term in latest_user_message.lower() for term in ("why did you assign", "why this exercise", "why this game", "why this task")):
        selected = min(measured_scores, key=measured_scores.get) if measured_scores else None
        exercise_map = {"memory flip": "WM", "focus sprint": "AT",
                        "pattern quest": "PS", "speed match": "SP"}
        mentioned_exercise = next((dim for label, dim in exercise_map.items()
                                   if label in latest_user_message.lower()), None)
        selected = mentioned_exercise or selected
        why_audit = anomaly_engine.explain_recommendation(measured_scores, selected)
        if why_audit.get("explainable"):
            answer = (f"Evidence-based reason: {why_audit['reason']} "
                      f"Measured scores (0–100): " +
                      ", ".join(f"{k}={v:g}" for k, v in why_audit["evidence"].items()) +
                      ". These are practice indicators, not a diagnosis.")
        else:
            answer = why_audit["reason"]
    if pushback["detected"]:
        answer += ("\n\nThanks for correcting me. Environmental distraction can affect a round, "
                   "so I will treat this result as uncertain rather than as proof of reduced ability. "
                   "You can take a short break and retry the same dimension when ready.")
    return jsonify(ok=True, reply=answer + (("\n\nCoach's note: " + out["reply"].split("\n\nCoach's note: ", 1)[1])
                   if "\n\nCoach's note: " in out["reply"] else ""),
                   answer=answer, collab=out["collab"], chat_sid=out["chat_sid"],
                   weakest=out["facts"]["weakest_dimension"],
                   safeguards={"pushback": pushback, "fortune_teller": forecast_guard, "why_audit": why_audit})


@app.get("/api/engagement")
def engagement_latest():
    return jsonify(ok=True, engagement=db.get_latest_engagement(request.args.get("user_id", "")))


@app.post("/api/mood")
def mood():
    """Auto-déclaration « Comment te sens-tu ? » (1 à 4)."""
    d = body()
    try:
        db.record_mood(d["user_id"], d["mood"])
    except (KeyError, TypeError, ValueError, PermissionError) as e:
        return jsonify(ok=False, error=str(e))
    return jsonify(ok=True)


@app.post("/api/engagement/feedback")
def engagement_feedback():
    """Droit de correction : « Il me semble que tu es un peu fatigué, est-ce juste ? »"""
    d = body()
    try:
        ok = db.record_engagement_feedback(d["user_id"], bool(d.get("agrees")), d.get("corrected_state"))
    except (KeyError, ValueError) as e:
        return jsonify(ok=False, error=str(e))
    return jsonify(ok=ok)


@app.post("/api/email-consent")
def email_consent():
    """Opt-in séparé pour les e-mails de relance (l'adresse est stockée à part)."""
    d = body()
    email = d.get("email")
    if not isinstance(email, str):
        return jsonify(ok=False, error="E-mail does not match this account."), 400
    email = email.strip().lower()
    if not email or user_id_for(email) != d.get("user_id"):  # l'e-mail doit correspondre au compte
        return jsonify(ok=False, error="E-mail does not match this account.")
    db.set_email_consent(d["user_id"], email, bool(d.get("consent")), d.get("name", ""))
    return jsonify(ok=True)


@app.get("/unsubscribe")
def unsubscribe():
    ok = db.unsubscribe(request.args.get("token", ""))
    msg = "You are unsubscribed. Your e-mail address has been deleted." if ok else \
          "This link is no longer active. You will not receive any more e-mails."
    return f"<!doctype html><meta charset=utf-8><title>AI4Brain</title><p style='font-family:sans-serif;margin:40px'>{msg}</p>"



@app.route("/api/tts", methods=["GET"])
def tts():
    text = request.args.get("text", "Hello, I am Brino.")
    
    # 1. SAFETY: Limit text length and clean weird characters
    text = text[:500] 
    text = text.replace("\n", " ").replace("*", "").replace("#", "")
    
    voice = "en-US-ChristopherNeural"
    
    async def generate_audio():
        communicate = edge_tts.Communicate(text, voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data
        
    try:
        # 2. SAFETY: Use a fresh event loop to prevent Flask threading crashes
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        audio_bytes = loop.run_until_complete(generate_audio())
        
        # 3. SAFETY: Return the audio
        return Response(audio_bytes, mimetype="audio/mpeg")
    except Exception as e:
        # This will print the EXACT error in your VS Code terminal if it fails
        print("🚨 TTS ERROR:", e)
        return jsonify(ok=False, error=str(e)), 500

if __name__ == "__main__":
    try:
        initialize_databases()
    except sqlite3.Error:
        traceback.print_exc()
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")