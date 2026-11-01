import json
import math
import os
import re
import secrets
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from statistics import median

# Chemin absolu vers la base de données
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "ai4brain.db"
SQL_PATH = BASE_DIR / "database1.sql"
CONFIG_PATH = BASE_DIR / "score_config-1.json"


class _ClosingConnection(sqlite3.Connection):
    """Keep sqlite's transaction context manager and close after its scope."""
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def get_connection():
    """Ouvre une connexion à la base de données."""
    conn = sqlite3.connect(str(DB_PATH), factory=_ClosingConnection)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_database():
    """Crée les tables à partir du fichier SQL (et migre une ancienne base)."""
    with get_connection() as conn:
        with open(SQL_PATH, "r", encoding="utf-8") as file:
            conn.executescript(file.read())
        # Migration : une base créée avant l'ajout d'email_consent n'a pas la colonne
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "email_consent" not in cols:
            conn.execute(
                "ALTER TABLE users ADD COLUMN email_consent INTEGER NOT NULL DEFAULT 0 "
                "CHECK (email_consent IN (0, 1))"
            )
        scols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "session_type" not in scols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN session_type TEXT NOT NULL DEFAULT 'game' "
                "CHECK (session_type IN ('game', 'collab'))"
            )
        conn.execute(
            "UPDATE cognitive_tasks SET reference_time_s = 1.2 "
            "WHERE task_name = 'symbol_matching' AND reference_time_s = 15"
        )


def ensure_user(user_id, pseudonym, consent=False):
    """Crée un utilisateur ou met à jour son consentement."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, pseudonym, consent_given, consent_date)
            VALUES (?, ?, ?, CASE WHEN ? = 1
                THEN CURRENT_TIMESTAMP ELSE NULL END)
            ON CONFLICT(user_id) DO UPDATE SET
                pseudonym = excluded.pseudonym,
                consent_given = excluded.consent_given,
                consent_date = CASE WHEN excluded.consent_given = 1
                    THEN COALESCE(users.consent_date, CURRENT_TIMESTAMP)
                    ELSE NULL END
            """,
            (user_id, pseudonym, int(consent), int(consent))
        )


def ensure_user_record(user_id, pseudonym):
    """Ensure an account has a pseudonym row without changing its consent state."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO users (user_id, pseudonym) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 pseudonym = CASE WHEN users.pseudonym IS NULL OR users.pseudonym = ''
                                  THEN excluded.pseudonym ELSE users.pseudonym END""",
            (user_id, pseudonym),
        )


def delete_user_data(user_id):
    """Delete a user's app data; related rows cascade from the users table."""
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        return cursor.rowcount > 0


def expired_user_ids():
    """List users whose last recorded activity is past their retention period."""
    with get_connection() as conn:
        return [r[0] for r in conn.execute(
            """SELECT u.user_id FROM users u
               WHERE datetime(
                 COALESCE((SELECT MAX(s.session_date) FROM sessions s WHERE s.user_id = u.user_id), u.created_at),
                 printf('+%d days', u.retention_days)
               ) <= CURRENT_TIMESTAMP"""
        ).fetchall()]


def delete_users(user_ids):
    """Delete user rows; related activity records are removed by SQLite cascades."""
    ids = list(set(user_ids or []))
    if not ids:
        return
    with get_connection() as conn:
        conn.executemany("DELETE FROM users WHERE user_id = ?", [(uid,) for uid in ids])


def delete_expired_users():
    """Delete expired users and return their IDs for cleanup in other stores."""
    expired = expired_user_ids()
    delete_users(expired)
    return expired


def save_game_session(user_id, game, score, response_time=None, hesitation_count=0, level=None,
                      correct_count=None, total_count=None):
    """Enregistre un résultat de jeu dans SQLite.

    `score` = précision brute du jeu (0-100). Le score cognitif final est calculé ici
    avec la formule de score_config-1.json > cognitive_scoring (pénalités de temps et d'hésitation).
    """
    with get_connection() as conn:
        user = conn.execute(
            "SELECT consent_given FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if not user or user[0] != 1:
            raise PermissionError(
                "Le consentement est nécessaire pour enregistrer les résultats."
            )

        ev = evaluate_attempt(game, score, response_time, hesitation_count, conn=conn, level=level)

        cursor = conn.execute(
            """
            INSERT INTO sessions (user_id, total_score, input_mode, session_type)
            VALUES (?, ?, 'non_biometric', 'game')
            """,
            (user_id, ev["score"])
        )

        session_id = cursor.lastrowid

        # Associe le résultat au catalogue des tâches cognitives
        task_names = {
            "Memory Flip": "reverse_digit_span",
            "Focus Sprint": "target_detection",
            "Pattern Quest": "number_sequence",
            "Speed Match": "symbol_matching",
        }

        task_name = task_names.get(game)

        if task_name:
            task = conn.execute(
                "SELECT id FROM cognitive_tasks WHERE task_name = ?",
                (task_name,)
            ).fetchone()

            if task:
                conn.execute(
                    """
                    INSERT INTO task_attempts (
                        session_id, task_id, difficulty_level,
                        correct, total, response_time, hesitation_count, score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        task[0],
                        ev["level"],
                        int(round(ev["accuracy"])) if correct_count is None else int(correct_count),
                        100 if total_count is None else int(total_count),
                        max(0.0, float(response_time or 0)),
                        max(0, int(hesitation_count or 0)),
                        ev["score"]
                    )
                )

        conn.execute(
            "INSERT INTO game_events (user_id, game, event) VALUES (?, ?, 'completed')",
            (user_id, game)
        )
        return session_id


# =====================================================================
#  ENGAGEMENT / MORAL  (EN, MO) -- calcul déterministe, le LLM ne fait que verbaliser
#  Tous les paramètres viennent de score_config-1.json > engagement_state
# =====================================================================

STATES = (
    "motivated_confident",
    "invested_under_pressure",
    "low_stimulation_routine",
    "low_energy",
    "neutral_to_confirm",
)


@lru_cache(maxsize=1)
def _config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def engagement_cfg():
    return _config()["engagement_state"]


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse(ts):
    return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# ---------- 1. Signaux (tous dans [0, 1]) ----------
def compute_signals(cfg, accuracy, response_time, t_ref, hesitations, past_scores,
                    days_away, usual_gap, abandon_rate, sessions_7d, account_is_new, current_score=None):
    p = cfg["params"]
    acc = _clamp(float(accuracy), 0, 100)
    s_t = acc if current_score is None else _clamp(float(current_score), 0, 100)  # S_t = score cognitif
    wrong = 1 - acc / 100

    t = float(response_time or 0)
    imp = _clamp(1 - t / (p["impulsivity_ref_ratio"] * t_ref)) if t > 0 else 0.0
    g_rand = imp * wrong                                     # rapide ET faux
    h = min(1.0, hesitations / p["hesitation_cap"])
    f = p["frustration_w_error"] * wrong + p["frustration_w_hesitation"] * h

    if past_scores:
        mean_prev = sum(past_scores) / len(past_scores)
        decline = _clamp((mean_prev - s_t) / p["decline_scale"])
        progress = _clamp((s_t - mean_prev) / p["progress_scale"])
    else:
        decline = progress = 0.0

    z = 1 - math.exp(-max(0.0, days_away - usual_gap) / p["inactivity_tau"])
    irregularity = 0.0 if account_is_new else 1 - min(1.0, sessions_7d / p["sessions_target_7d"])

    return {"Imp": imp, "G": g_rand, "H": h, "F": f, "L": decline, "P": progress,
            "Z": z, "Q": abandon_rate, "Ir": irregularity}


# ---------- 2. Axes ----------
def compute_axes(cfg, sig):
    w = cfg["axes"]["weights"]
    en = 100 * (1 - w["EN"]["Z"] * sig["Z"] - w["EN"]["Q"] * sig["Q"]
                - w["EN"]["G"] * sig["G"] - w["EN"]["Ir"] * sig["Ir"])
    mo = (100 * (1 - w["MO"]["F"] * sig["F"] - w["MO"]["L"] * sig["L"] - w["MO"]["H"] * sig["H"])
          + w["MO"]["P_bonus"] * sig["P"])
    return _clamp(en, 0, 100), _clamp(mo, 0, 100)


# ---------- 3. Lissage avec incertitude (même mécanique que le Brain Twin) ----------
def smooth(cfg, x_obs, x_old, u_old):
    sm = cfg["smoothing"]
    p_new = 1 / sm["obs_uncertainty"] ** 2
    if x_old is None:
        return x_obs, sm["obs_uncertainty"]
    p_old = 1 / max(u_old, 1e-6) ** 2
    denom = sm["forgetting"] * p_old + p_new
    x_new = (sm["forgetting"] * p_old * x_old + p_new * x_obs) / denom
    return x_new, max(sm["min_uncertainty"], math.sqrt(1 / denom))


# ---------- 4. Quadrants ----------
def classify(cfg, en, mo, u):
    c = cfg["classification"]["center"]
    if abs(en - c) <= u or abs(mo - c) <= u:
        return "neutral_to_confirm"
    return {
        (True, True): "motivated_confident",
        (True, False): "invested_under_pressure",
        (False, True): "low_stimulation_routine",
        (False, False): "low_energy",
    }[(en > c, mo > c)]


def _abandon_rate(conn, user_id, window):
    """Part des `window` dernières parties commencées qui n'ont pas été terminées."""
    starts = conn.execute(
        "SELECT id FROM game_events WHERE user_id = ? AND event = 'started' "
        "ORDER BY id DESC LIMIT ?", (user_id, window)).fetchall()
    if not starts:
        return 0.0
    first_id = min(r[0] for r in starts)
    events = conn.execute(
        "SELECT game, event FROM game_events WHERE user_id = ? AND id >= ? ORDER BY id",
        (user_id, first_id)).fetchall()
    abandoned, pending = 0, None
    for game, event in events:
        if event == "started":
            if pending is not None:
                abandoned += 1
            pending = game
        elif event == "completed" and pending == game:
            pending = None
    if pending is not None:
        abandoned += 1
    return min(1.0, abandoned / len(starts))


def log_game_event(user_id, game, event="started"):
    """Appelé quand une partie commence (l'événement 'completed' est écrit par save_game_session)."""
    with get_connection() as conn:
        row = conn.execute("SELECT consent_given FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row[0] != 1:
            raise PermissionError("Consent required.")
        conn.execute("INSERT INTO game_events (user_id, game, event) VALUES (?, ?, ?)",
                     (user_id, game, event))


def compute_engagement_state(user_id, session_id=None, now=None, persist=True):
    """Calcule EN / MO / état pour la session donnée (par défaut : la dernière).

    persist=True  : enregistre dans engagement_history (appel après chaque partie).
    persist=False : calcul « à l'instant T » sans écriture (tableau de bord, vérification avant e-mail).
    Retourne None si on ne peut rien calculer (pas de session / jeu inconnu).
    """
    cfg = engagement_cfg()
    now = now or _utcnow()

    with get_connection() as conn:
        row = conn.execute("SELECT consent_given FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row[0] != 1:
            raise PermissionError("Consent required to compute engagement.")

        query = """
            SELECT s.id, s.session_date, a.score, a.response_time, a.hesitation_count, t.reference_time_s,
                   100.0 * a.correct / a.total
            FROM sessions s
            JOIN task_attempts a ON a.session_id = s.id
            JOIN cognitive_tasks t ON t.id = a.task_id
            WHERE s.user_id = ? AND s.session_type = 'game' {extra}
            ORDER BY s.id DESC LIMIT 1"""
        cur = conn.execute(query.format(extra="AND s.id = ?" if session_id else ""),
                           (user_id, session_id) if session_id else (user_id,)).fetchone()
        if not cur:
            return None
        sid, _sdate, score, rtime, hes, t_ref, accuracy = cur

        # Historique des scores précédents (S_{t-3..t-1})
        past = [r[0] for r in conn.execute(
            "SELECT total_score FROM sessions WHERE user_id = ? AND id < ? AND total_score IS NOT NULL "
            "AND session_type = 'game' "
            "ORDER BY id DESC LIMIT ?", (user_id, sid, cfg["params"]["history_window"]))]

        # Rythme : écart médian habituel g, jours depuis la dernière session d, sessions sur 7 jours
        dates = [_parse(r[0]) for r in conn.execute(
            "SELECT session_date FROM sessions WHERE user_id = ? AND session_type = 'game' ORDER BY id",
            (user_id,))]
        gaps = [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]
        usual_gap = median(gaps) if len(gaps) >= 2 else cfg["params"]["default_gap_days"]
        days_away = max(0.0, (now - dates[-1]).total_seconds() / 86400)
        sessions_7d = sum(1 for d in dates if (now - d).total_seconds() <= 7 * 86400)
        account_is_new = (now - dates[0]).total_seconds() < 7 * 86400

        abandon = _abandon_rate(conn, user_id, cfg["params"]["abandon_window"])

        sig = compute_signals(cfg, accuracy, rtime, t_ref, hes or 0, past, days_away, usual_gap,
                              abandon, sessions_7d, account_is_new, current_score=score)
        en_obs, mo_obs = compute_axes(cfg, sig)

        # Dernier état connu (hors la session en cours de calcul)
        prev = conn.execute(
            "SELECT en, mo, uncertainty, n_obs, candidate_state, state FROM engagement_history "
            "WHERE user_id = ? AND (session_id IS NULL OR session_id != ?) ORDER BY id DESC LIMIT 1",
            (user_id, sid)).fetchone()

        if prev:
            en, u_en = smooth(cfg, en_obs, prev[0], prev[2])
            mo, u_mo = smooth(cfg, mo_obs, prev[1], prev[2])
            n_obs = prev[3] + 1
        else:
            (en, u_en), (mo, u_mo) = smooth(cfg, en_obs, None, None), smooth(cfg, mo_obs, None, None)
            n_obs = 1
        u = max(u_en, u_mo)

        candidate = classify(cfg, en, mo, u)
        # Pour changer d'état : 2 sessions consécutives dans le nouveau quadrant (anti-oscillation)
        if not prev:
            state = candidate
        elif candidate == prev[5] or candidate == prev[4]:
            state = candidate
        else:
            state = prev[5]

        result = {
            "session_id": sid,
            "EN": round(en, 1), "MO": round(mo, 1), "uncertainty": round(u, 1),
            "EN_observed": round(en_obs, 1), "MO_observed": round(mo_obs, 1),
            "n_obs": n_obs, "candidate": candidate, "state": state,
            "signals": {k: round(v, 3) for k, v in sig.items()},
            "days_away": round(days_away, 1), "usual_gap_days": round(usual_gap, 1),
            "strategy": cfg["classification"]["states"][state],
            "display": f"EN = {en:.0f} ± {u:.0f} · MO = {mo:.0f} ± {u:.0f}",
        }

        if persist:
            conn.execute("DELETE FROM engagement_history WHERE session_id = ?", (sid,))
            conn.execute(
                """INSERT INTO engagement_history
                   (user_id, session_id, en, mo, uncertainty, n_obs, candidate_state, state, signals_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, sid, en, mo, u, n_obs, candidate, state, json.dumps(result["signals"])))
        return result


def get_latest_engagement(user_id):
    with get_connection() as conn:
        r = conn.execute(
            "SELECT en, mo, uncertainty, state, n_obs, created_at FROM engagement_history "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    if not r:
        return None
    return {"EN": round(r[0], 1), "MO": round(r[1], 1), "uncertainty": round(r[2], 1),
            "state": r[3], "n_obs": r[4], "created_at": r[5]}


# ---------- Auto-déclaration, droit de correction, calibrage ----------
def record_mood(user_id, mood_level, session_id=None):
    """Enregistre le « Comment te sens-tu ? » (1 à 4). Rattaché à la dernière session par défaut."""
    mood_level = int(mood_level)
    if not 1 <= mood_level <= 4:
        raise ValueError("mood_level must be between 1 and 4")
    with get_connection() as conn:
        row = conn.execute("SELECT consent_given FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row[0] != 1:
            raise PermissionError("Consent required.")
        if session_id is None:
            r = conn.execute("SELECT MAX(id) FROM sessions WHERE user_id = ? AND session_type = 'game'",
                             (user_id,)).fetchone()
            session_id = r[0]
        conn.execute("INSERT INTO mood_reports (user_id, session_id, mood_level) VALUES (?, ?, ?)",
                     (user_id, session_id, mood_level))


def record_engagement_feedback(user_id, agrees, corrected_state=None):
    """Droit de correction : « Il me semble que tu es un peu fatigué, est-ce juste ? »"""
    if not agrees and corrected_state not in STATES:
        raise ValueError("corrected_state must be one of " + ", ".join(STATES))
    with get_connection() as conn:
        r = conn.execute("SELECT id FROM engagement_history WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                         (user_id,)).fetchone()
        if not r:
            return False
        if agrees:
            conn.execute("UPDATE engagement_history SET user_feedback = 'confirmed' WHERE id = ?", (r[0],))
        else:  # l'utilisateur a raison : l'état est corrigé
            conn.execute(
                "UPDATE engagement_history SET user_feedback = 'corrected', state = ?, candidate_state = ? "
                "WHERE id = ?", (corrected_state, corrected_state, r[0]))
        return True


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def engagement_calibration(user_id=None):
    """Mesure si la formule colle à ce que disent les utilisateurs (à mettre dans le rapport)."""
    where, args = ("WHERE e.user_id = ?", (user_id,)) if user_id else ("", ())
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT e.mo, m.mood_level FROM engagement_history e "
            f"JOIN mood_reports m ON m.session_id = e.session_id {where}", args).fetchall()
        fb = conn.execute(
            f"SELECT user_feedback, COUNT(*) FROM engagement_history e "
            f"{where + (' AND' if where else 'WHERE')} user_feedback IS NOT NULL GROUP BY user_feedback",
            args).fetchall()
    fb = dict(fb)
    answered = sum(fb.values())
    return {
        "n_mood_reports": len(rows),
        "pearson_MO_vs_mood": _pearson([r[0] for r in rows], [r[1] for r in rows]),
        "feedback_confirmed_rate": (fb.get("confirmed", 0) / answered) if answered else None,
        "n_feedback": answered,
    }


# ---------- E-mail : consentement séparé ----------
def set_email_consent(user_id, email, consent, pseudonym=""):
    """Opt-in e-mail séparé. L'adresse est stockée à part et supprimée au retrait du consentement."""
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, pseudonym) VALUES (?, ?)", (user_id, pseudonym))
        if consent:
            conn.execute("UPDATE users SET email_consent = 1 WHERE user_id = ?", (user_id,))
            conn.execute(
                """INSERT INTO user_contacts (user_id, email, unsubscribe_token)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET email = excluded.email""",
                (user_id, email.strip().lower(), secrets.token_urlsafe(24)))
        else:
            conn.execute("UPDATE users SET email_consent = 0 WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM user_contacts WHERE user_id = ?", (user_id,))


def get_email_consent(user_id):
    with get_connection() as conn:
        r = conn.execute("SELECT email_consent FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return bool(r and r[0])


def unsubscribe(token):
    """Lien de désinscription présent dans chaque e-mail."""
    with get_connection() as conn:
        r = conn.execute("SELECT user_id FROM user_contacts WHERE unsubscribe_token = ?", (token,)).fetchone()
        if not r:
            return False
        conn.execute("UPDATE users SET email_consent = 0 WHERE user_id = ?", (r[0],))
        conn.execute("DELETE FROM user_contacts WHERE user_id = ?", (r[0],))
        return True


# ---------- E-mail : déclencheur ----------
def should_send_email(conn, user_id, now=None):
    """Envoyer si : consentements ET d >= max(7, 2g) ET dernier e-mail > 14 j ET e-mails sans réponse < 3."""
    ecfg = engagement_cfg()["email"]
    now = now or _utcnow()

    u = conn.execute("SELECT consent_given, email_consent FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not u or u[0] != 1 or u[1] != 1:
        return False, "no consent"

    dates = [_parse(r[0]) for r in conn.execute(
        "SELECT session_date FROM sessions WHERE user_id = ? AND session_type = 'game' ORDER BY id",
        (user_id,))]
    if not dates:
        return False, "no session yet"
    gaps = [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]
    g = median(gaps) if len(gaps) >= 2 else engagement_cfg()["params"]["default_gap_days"]
    d = (now - dates[-1]).total_seconds() / 86400
    if d < max(ecfg["min_days_away"], ecfg["gap_multiplier"] * g):
        return False, f"not away long enough (d={d:.1f})"

    last_mail = conn.execute(
        "SELECT MAX(sent_at) FROM notification_log WHERE user_id = ? AND status IN ('sent', 'dry_run')",
        (user_id,)).fetchone()[0]
    if last_mail and (now - _parse(last_mail)).total_seconds() / 86400 <= ecfg["cooldown_days"]:
        return False, "cooldown"

    unanswered = conn.execute(
        "SELECT COUNT(*) FROM notification_log WHERE user_id = ? AND status IN ('sent', 'dry_run') "
        "AND sent_at > ?", (user_id, dates[-1].strftime("%Y-%m-%d %H:%M:%S"))).fetchone()[0]
    if unanswered >= ecfg["max_unanswered"]:
        return False, "too many unanswered e-mails"
    return True, f"d={d:.1f} days"


# ---------- E-mail : message (modèle fixe + reformulation LLM optionnelle) ----------
EMAIL_TEMPLATES = {
    "motivated_confident": {
        "subject": "{name}, ready for a fresh challenge?",
        "opening": "Your last sessions looked steady and confident, and it has been {days} days since your last round.",
        "why": "I'm writing because your recent rounds suggest you were enjoying the pace, so a slightly harder challenge may feel rewarding.",
        "tips": ["Try your favourite game one level up for a single round.",
                 "Set a small goal, for example beating your previous best by a few points."],
    },
    "invested_under_pressure": {
        "subject": "{name}, a gentle round whenever you like",
        "opening": "You put real effort into your last sessions, and it has been {days} days since your last round.",
        "why": "I'm writing because your recent rounds suggest you were working hard, so an easier, calmer round could help you feel at ease again.",
        "tips": ["Start with one round one level lower and focus on getting it right, not on speed.",
                 "Take a slow breath before you begin and re-read each question once."],
    },
    "low_stimulation_routine": {
        "subject": "{name}, time to mix things up?",
        "opening": "Your last sessions went smoothly, and it has been {days} days since your last round.",
        "why": "I'm writing because your recent rounds suggest the games may have started to feel routine, so some variety could bring back the spark.",
        "tips": ["Pick a game you haven't played this week.",
                 "Raise the difficulty by one level to keep it interesting."],
    },
    "low_energy": {
        "subject": "{name}, just two minutes today?",
        "opening": "It has been {days} days since your last round, and that is perfectly fine.",
        "why": "I'm writing because your recent rounds suggest you might be short on energy, so a very small step could be enough to get back into the rhythm.",
        "tips": ["Play a single 2-minute round, nothing more.",
                 "Choose the game you enjoy most and aim only to finish it."],
    },
    "neutral_to_confirm": {
        "subject": "{name}, a quick hello from your coach",
        "opening": "It has been {days} days since your last round.",
        "why": "I'm writing because I don't have enough information yet to know how your last sessions felt, and I'd rather ask than guess.",
        "tips": ["Play one short round of any game you like.",
                 "Afterwards, tell me how you felt with the quick emoji check-in, so I can adapt."],
    },
}


def forbidden_terms_found(text):
    """Même contrôle que coach.post_check (config) + liste anglaise/française supplémentaire."""
    terms = list(_config()["coach"]["forbidden_terms"]) + list(engagement_cfg()["email"]["forbidden_terms_extra"])
    return [t for t in terms if re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.IGNORECASE)]


def build_reengagement_email(name, state, days_away, unsubscribe_url, llm_rewrite=None):
    """Retourne (sujet, corps). Le contenu vient d'un modèle déterministe ; un LLM peut seulement
    le reformuler. Tout texte contenant un terme interdit est rejeté (3 essais) puis remplacé par le modèle."""
    tpl = EMAIL_TEMPLATES[state]
    subject = tpl["subject"].format(name=name or "there")
    body = (
        f"Hi {name or 'there'},\n\n"
        f"{tpl['opening'].format(days=int(days_away))}\n\n"
        f"Why you're getting this: {tpl['why']} This is only an estimate based on how you played, and I may be wrong.\n\n"
        f"Two things you can try:\n1. {tpl['tips'][0]}\n2. {tpl['tips'][1]}\n\n"
        f"No pressure at all. Come back whenever it suits you.\n\n"
        f"Your AI4Brain coach\n\n"
        f"You receive this because you opted in to reminder e-mails. Unsubscribe any time: {unsubscribe_url}\n"
    )
    if llm_rewrite:
        for _ in range(3):
            try:
                candidate = llm_rewrite(body, state)
            except Exception:
                break
            if candidate and not forbidden_terms_found(candidate) and unsubscribe_url in candidate:
                return subject, candidate
    assert not forbidden_terms_found(subject + body), "template contains a forbidden term"
    return subject, body


def _send_smtp(to_addr, subject, body):
    """Envoie via SMTP si SMTP_HOST est défini, sinon simule ('dry_run')."""
    host = os.getenv("SMTP_HOST")
    if not host:
        return "dry_run"
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM", "coach@ai4brain.local")
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
            smtp.starttls()
            if os.getenv("SMTP_USER"):
                smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return "sent"
    except Exception:
        return "failed"


def send_due_emails(now=None, llm_rewrite=None, sender=_send_smtp):
    """À lancer une fois par jour (cron / planificateur). Retourne la liste des e-mails traités."""
    now = now or _utcnow()
    base_url = os.getenv("APP_BASE_URL", "http://localhost:5000")
    report = []
    with get_connection() as conn:
        users = conn.execute(
            """SELECT u.user_id, u.pseudonym, c.email, c.unsubscribe_token
               FROM users u JOIN user_contacts c ON c.user_id = u.user_id
               WHERE u.consent_given = 1 AND u.email_consent = 1""").fetchall()
        for user_id, pseudonym, email, token in users:
            ok, reason = should_send_email(conn, user_id, now)
            if not ok:
                report.append((user_id[:8], "skipped", reason))
                continue
            last = conn.execute("SELECT state FROM engagement_history WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                                (user_id,)).fetchone()
            state = last[0] if last else "neutral_to_confirm"
            last_session = conn.execute("SELECT MAX(session_date) FROM sessions WHERE user_id = ? AND session_type = 'game'",
                                        (user_id,)).fetchone()[0]
            days = (now - _parse(last_session)).total_seconds() / 86400
            first_name = (pseudonym or "").split(" ")[0]
            subject, body = build_reengagement_email(
                first_name, state, days, f"{base_url}/unsubscribe?token={token}", llm_rewrite)
            status = sender(email, subject, body)
            conn.execute(
                "INSERT INTO notification_log (user_id, state, subject, status, sent_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, state, subject, status, now.strftime("%Y-%m-%d %H:%M:%S")))
            report.append((user_id[:8], status, state))
    return report



# =====================================================================
#  SCORE COGNITIF + BRAIN TWIN + POINT FAIBLE  (une seule logique : score_config-1.json)
# =====================================================================

DIM_NAMES = {"WM": "Working Memory", "AT": "Attention", "PS": "Problem Solving", "SP": "Processing Speed"}
GAME_DIMENSIONS = ("WM", "AT", "PS", "SP")


def cognitive_score(accuracy, response_time, t_ref, hesitations, level=None):
    """Score = clamp((Acc - P_t - P_h) * difficulty_weight, 0, 100)   [cognitive_scoring]"""
    cs = _config()["cognitive_scoring"]
    prm = cs["params"]
    level = level or prm["default_difficulty_level"]
    acc = _clamp(float(accuracy), 0, 100)
    t = float(response_time or 0)
    p_t = 0.0
    if t > prm["speed_threshold_ratio"] * t_ref:
        p_t = min(prm["speed_penalty_max"], prm["speed_penalty_slope"] * (t / t_ref - prm["speed_threshold_ratio"]))
    p_h = min(prm["hesitation_penalty_max"], prm["hesitation_penalty_per_unit"] * int(hesitations or 0))
    score = _clamp((acc - p_t - p_h) * cs["difficulty_weight"][str(level)], 0, 100)
    return {"score": round(score, 2), "accuracy": acc, "speed_penalty": round(p_t, 2),
            "hesitation_penalty": float(p_h), "level": level, "error_rate": round(100 - acc, 2)}


def evaluate_attempt(game, accuracy, response_time=None, hesitations=0, conn=None, level=None):
    """Calcule le score cognitif d'un jeu, sans rien écrire. Ajoute dimension et temps de référence."""
    dim = _config()["cognitive_scoring"]["game_to_dimension"].get(game)
    close = conn is None
    conn = conn or get_connection()
    try:
        task_names = {"Memory Flip": "reverse_digit_span", "Focus Sprint": "target_detection",
                      "Pattern Quest": "number_sequence", "Speed Match": "symbol_matching"}
        row = conn.execute("SELECT reference_time_s FROM cognitive_tasks WHERE task_name = ?",
                           (task_names.get(game),)).fetchone()
    finally:
        if close:
            conn.close()
    t_ref = row[0] if row else {"WM": 20, "AT": 30, "PS": 45, "SP": 1.2}.get(dim, 30)
    res = cognitive_score(accuracy, response_time, t_ref, hesitations, level=level)
    res.update({"dimension": dim, "t_ref": t_ref})
    return res


def twin_step(prev, x):
    """Mise à jour du Brain Twin pondérée par la précision (brain_twin.update). prev = dict ou None."""
    bt = _config()["engagement_state"]["smoothing"]       # mêmes constantes : 10, 0.95, plancher 3
    p_new = 1 / bt["obs_uncertainty"] ** 2
    if not prev:
        score, u, n = float(x), float(bt["obs_uncertainty"]), 1
    else:
        p_old = 1 / max(float(prev["uncertainty"]), 1e-6) ** 2
        denom = bt["forgetting"] * p_old + p_new
        score = (bt["forgetting"] * p_old * float(prev["score"]) + p_new * float(x)) / denom
        u = max(bt["min_uncertainty"], math.sqrt(1 / denom))
        n = int(prev.get("n_tests", 1)) + 1
    return {"score": round(score, 2), "uncertainty": round(u, 2), "n_tests": n,
            "ci_low": round(max(0.0, score - 1.96 * u), 2), "ci_high": round(min(100.0, score + 1.96 * u), 2)}


def update_brain_twin(user_id, session_id, dimension, score, prev_override=None):
    """Écrit une ligne d'historique du Brain Twin. prev_override : état venant du navigateur si la base est vide."""
    with get_connection() as conn:
        r = conn.execute(
            "SELECT score, uncertainty, n_tests FROM brain_twin_history "
            "WHERE user_id = ? AND dimension = ? AND is_projection = 0 ORDER BY id DESC LIMIT 1",
            (user_id, dimension)).fetchone()
        prev = {"score": r[0], "uncertainty": r[1], "n_tests": r[2]} if r else prev_override
        new = twin_step(prev, score)
        conn.execute(
            """INSERT INTO brain_twin_history
               (user_id, session_id, dimension, score, uncertainty, ci_low, ci_high, n_tests, is_projection)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (user_id, session_id, dimension, new["score"], new["uncertainty"],
             new["ci_low"], new["ci_high"], new["n_tests"]))
    return new


def get_brain_twin(user_id):
    """Dernier état de chaque dimension : {WM: {score, uncertainty, ci_low, ci_high, n_tests}, ...}."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT dimension, score, uncertainty, ci_low, ci_high, n_tests FROM brain_twin_history b
               WHERE user_id = ? AND is_projection = 0
                 AND id = (SELECT MAX(id) FROM brain_twin_history
                           WHERE user_id = b.user_id AND dimension = b.dimension AND is_projection = 0)""",
            (user_id,)).fetchall()
    return {d: {"score": s, "uncertainty": u, "ci_low": lo, "ci_high": hi, "n_tests": n}
            for d, s, u, lo, hi, n in rows}


def detect_weakness(twin):
    """Algorithme déterministe (le LLM ne fait que verbaliser) : priority = (100 - score) + 0.5 * u.
    Une dimension jamais mesurée a score 0 et u = 10 : elle passe en priorité (« mesurer d'abord »)."""
    prior_u = _config()["engagement_state"]["smoothing"]["obs_uncertainty"]
    prio, measured = {}, {}
    for d in GAME_DIMENSIONS:
        t = (twin or {}).get(d)
        if t:
            measured[d] = t["score"]
            prio[d] = (100 - t["score"]) + 0.5 * t["uncertainty"]
        else:
            prio[d] = 100 + 0.5 * prior_u
    weakest = max(prio, key=prio.get)
    strongest = max(measured, key=measured.get) if measured else None
    overall = round(sum(measured.values()) / len(measured), 1) if measured else 0.0
    return {"weakest": weakest, "weakest_name": DIM_NAMES[weakest],
            "strongest": strongest, "strongest_name": DIM_NAMES.get(strongest),
            "priorities": {d: round(v, 1) for d, v in prio.items()},
            "measured": sorted(measured), "overall": overall}


def twin_view(twin):
    """Format envoyé à l'interface : twin + point faible/fort + score global."""
    return {"dimensions": twin, **detect_weakness(twin)}


# =====================================================================
#  AI COLLABORATION SCORE  (0-100)  -- agrégation 100 % déterministe
# =====================================================================

COLLAB_DIMS = ("C", "V", "I", "A", "R")


def collab_indicator_map():
    """{indicator_name: dimension} lu dans la config."""
    return {ind: d for d, spec in _config()["dimensions"].items() for ind in spec["indicators"]}


def normalize_indicators(raw):
    """Valide la notation brute (LLM ou règles) : valeurs autorisées, confiance, preuve exigée pour la note 1."""
    levels = _config()["indicator_scoring"]["confidence_levels"]
    allowed_conf = set(levels.values())
    out = {}
    for name in collab_indicator_map():
        r = (raw or {}).get(name) or {}
        s = r.get("score")
        s = s if s in (0, 0.5, 1) else None                      # sinon : non évaluable
        c = r.get("confidence", 1.0)
        c = levels.get(c, c) if isinstance(c, str) else c
        c = c if c in allowed_conf else 0.5
        ev = (r.get("evidence") or "").strip() or None
        if s == 1 and not ev:                                     # evidence_required_for_score_1
            s = 0.5
        out[name] = {"score": s, "confidence": c, "evidence": ev}
    return out


def aggregate_collaboration(indicators, prev_score=None, n_sessions=1):
    """D = 100*sum(s*c)/sum(c) -> shrinkage -> S_base -> synergie/pénalité -> lissage -> incertitude."""
    cfg = _config()
    agg, inno = cfg["aggregation"], cfg["innovations"]
    k, prior = agg["shrinkage"]["k"], agg["shrinkage"]["prior"]
    ind = normalize_indicators(indicators)
    imap = collab_indicator_map()

    dims = {}
    for d in COLLAB_DIMS:
        obs = [(v["score"], v["confidence"]) for n, v in ind.items() if imap[n] == d and v["score"] is not None]
        n = len(obs)
        if n < agg["min_evaluable_indicators"]:
            dims[d] = {"available": False, "n": n, "D": None, "D_adj": None}
            continue
        D = 100 * sum(s * c for s, c in obs) / sum(c for _, c in obs)
        dims[d] = {"available": True, "n": n, "D": round(D, 2), "D_adj": round((n * D + k * prior) / (n + k), 2)}

    avail = {d: v for d, v in dims.items() if v["available"]}
    if not avail:
        return {"S": None, "available": False, "dimensions": dims, "indicators": ind,
                "note": "not enough evaluable indicators yet"}

    W = {d: cfg["dimensions"][d]["weight"] for d in avail}
    s_base = sum(W[d] * avail[d]["D_adj"] for d in avail) / sum(W.values())

    synergy = penalty = 0.0
    if "V" in avail and "I" in avail:
        V, I = avail["V"]["D_adj"], avail["I"]["D_adj"]
        if V >= 70 and I >= 70:
            synergy = min(5, 0.1 * (min(V, I) - 70))
    if "A" in avail and "V" in avail:
        A, V = avail["A"]["D_adj"], avail["V"]["D_adj"]
        if A < 40 and V < 40:
            penalty = min(15, 0.3 * (40 - A))
    s_final = _clamp(s_base + synergy - penalty, 0, 100)
    s = s_final if prev_score is None else 0.7 * s_final + 0.3 * float(prev_score)   # temporal_smoothing
    u = max(3, 10 / (1 + 0.5 * (max(1, n_sessions) - 1)))                              # uncertainty

    band = next(label for hi, label in ((30, "needs_work"), (65, "average"), (85, "good"), (100, "excellent"))
                if s <= hi)
    return {"S": round(s, 1), "S_base": round(s_base, 1), "synergy_bonus": round(synergy, 2),
            "dependency_penalty": round(penalty, 2), "S_final": round(s_final, 1),
            "uncertainty": round(u, 1), "band": band, "available": True,
            "dimensions": dims, "indicators": ind,
            "display": f"S = {s:.0f} ± {u:.0f}"}


def save_collaboration_session(user_id, indicators, session_id=None):
    """Persiste un score de collaboration (sessions.session_type='collab'). Réutilise la même session
    tant que la conversation continue (session_id), pour ne pas créer une ligne par message."""
    cfg = _config()
    with get_connection() as conn:
        row = conn.execute("SELECT consent_given FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row or row[0] != 1:
            raise PermissionError("Consent required to save the collaboration score.")

        if session_id is not None:
            ok = conn.execute("SELECT 1 FROM sessions WHERE id = ? AND user_id = ? AND session_type = 'collab'",
                              (session_id, user_id)).fetchone()
            if not ok:
                session_id = None
        limit_id = session_id if session_id is not None else 10 ** 12
        prev = conn.execute(
            "SELECT total_score FROM sessions WHERE user_id = ? AND session_type = 'collab' AND id < ? "
            "AND total_score IS NOT NULL ORDER BY id DESC LIMIT 1", (user_id, limit_id)).fetchone()
        n_prev = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND session_type = 'collab' "
                              "AND id < ?", (user_id, limit_id)).fetchone()[0]
        res = aggregate_collaboration(indicators, prev[0] if prev else None, n_prev + 1)
        if not res["available"]:
            return res

        if session_id is None:
            session_id = conn.execute(
                "INSERT INTO sessions (user_id, input_mode, session_type) VALUES (?, 'non_biometric', 'collab')",
                (user_id,)).lastrowid
        else:
            conn.execute("DELETE FROM indicator_scores WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM dimension_scores WHERE session_id = ?", (session_id,))

        imap = collab_indicator_map()
        for name, v in res["indicators"].items():
            conn.execute(
                "INSERT INTO indicator_scores (session_id, dimension, indicator_name, score, confidence, evidence) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, imap[name], name, v["score"], v["confidence"], v["evidence"]))
        for d, v in res["dimensions"].items():
            if v["available"]:
                conn.execute(
                    "INSERT INTO dimension_scores (session_id, dimension, score, weight, n_indicators) "
                    "VALUES (?, ?, ?, ?, ?)", (session_id, d, v["D_adj"], cfg["dimensions"][d]["weight"], v["n"]))
        # Les triggers ont écrit S_base ; on remplace par le score final (bonus, pénalité, lissage)
        conn.execute("UPDATE sessions SET total_score = ?, score_uncertainty = ? WHERE id = ?",
                     (res["S"], res["uncertainty"], session_id))
    res["session_id"] = session_id
    return res


def save_coach_feedback(user_id, message, justification, target_dimension=None, language="en"):
    """Archive un message du coach (le CHECK SQL garantit clinical_term_detected = 0)."""
    if forbidden_terms_found(message + " " + justification):
        raise ValueError("clinical term detected")
    with get_connection() as conn:
        r = conn.execute("SELECT MAX(id) FROM sessions WHERE user_id = ? AND session_type = 'game'",
                         (user_id,)).fetchone()
        if not r or r[0] is None:
            return None
        return conn.execute(
            "INSERT INTO coach_feedback (session_id, language, message, justification, target_dimension) "
            "VALUES (?, ?, ?, ?, ?)", (r[0], language, message, justification, target_dimension)).lastrowid


if __name__ == "__main__":
    import sys
    init_database()
    if len(sys.argv) > 1 and sys.argv[1] == "send-emails":
        for line in send_due_emails():
            print(line)
    else:
        print("Usage: python database1.py send-emails")
