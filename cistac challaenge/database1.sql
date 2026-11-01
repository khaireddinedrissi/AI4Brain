PRAGMA foreign_keys = ON;

-- 0. Utilisateurs (pseudonymes uniquement) + consentement et rétention
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    pseudonym TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    consent_given INTEGER NOT NULL DEFAULT 0 CHECK (consent_given IN (0, 1)),
    consent_date TEXT,
    retention_days INTEGER NOT NULL DEFAULT 365 CHECK (retention_days > 0),
    preferred_input_mode TEXT NOT NULL DEFAULT 'non_biometric'
        CHECK (preferred_input_mode IN ('non_biometric', 'voice', 'camera')),
    email_consent INTEGER NOT NULL DEFAULT 0 CHECK (email_consent IN (0, 1))
);

CREATE TABLE IF NOT EXISTS consent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('granted', 'withdrawn', 'deletion_requested')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 1. Historique des sessions
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    input_mode TEXT NOT NULL DEFAULT 'non_biometric'
        CHECK (input_mode IN ('non_biometric', 'voice', 'camera')),
    total_score REAL
        CHECK (total_score BETWEEN 0 AND 100),
    score_uncertainty REAL CHECK (score_uncertainty >= 0),
    session_type TEXT NOT NULL DEFAULT 'game' CHECK (session_type IN ('game', 'collab')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- 2. Notes des indicateurs (AI Collaboration Score)
CREATE TABLE IF NOT EXISTS indicator_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    dimension TEXT NOT NULL
        CHECK (dimension IN ('C', 'V', 'I', 'A', 'R')),
    indicator_name TEXT NOT NULL,
    score REAL
        CHECK (
            score IN (0, 0.5, 1)
            OR score IS NULL
        ),
    confidence REAL NOT NULL DEFAULT 1.0
        CHECK (confidence IN (0.5, 0.75, 1.0)),
    evidence TEXT,
    CHECK (score IS NOT 1 OR (evidence IS NOT NULL AND length(evidence) > 0)),
    FOREIGN KEY (session_id)
        REFERENCES sessions(id)
        ON DELETE CASCADE,
    UNIQUE (session_id, indicator_name)
);

-- 3. Scores des cinq dimensions
CREATE TABLE IF NOT EXISTS dimension_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    dimension TEXT NOT NULL
        CHECK (dimension IN ('C', 'V', 'I', 'A', 'R')),
    score REAL NOT NULL
        CHECK (score BETWEEN 0 AND 100),
    weight REAL NOT NULL
        CHECK (weight BETWEEN 0 AND 1),
    n_indicators INTEGER NOT NULL DEFAULT 3 CHECK (n_indicators BETWEEN 0 AND 3),
    FOREIGN KEY (session_id)
        REFERENCES sessions(id)
        ON DELETE CASCADE,
    UNIQUE (session_id, dimension)
);

-- 4. Catalogue des tâches cognitives (documentation par dimension)
CREATE TABLE IF NOT EXISTS cognitive_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension TEXT NOT NULL CHECK (dimension IN ('WM', 'AT', 'PS', 'SP')),
    task_name TEXT NOT NULL UNIQUE,
    definition TEXT,
    reference_time_s REAL NOT NULL CHECK (reference_time_s > 0),
    known_biases TEXT
);

-- 5. Résultats des tâches (score, temps, erreurs, comportement)
CREATE TABLE IF NOT EXISTS task_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    difficulty_level INTEGER NOT NULL CHECK (difficulty_level BETWEEN 1 AND 5),
    correct INTEGER NOT NULL CHECK (correct >= 0),
    total INTEGER NOT NULL CHECK (total > 0),
    response_time REAL NOT NULL CHECK (response_time >= 0),
    hesitation_count INTEGER NOT NULL DEFAULT 0 CHECK (hesitation_count >= 0),
    error_rate REAL GENERATED ALWAYS AS (100.0 * (total - correct) / total) VIRTUAL,
    score REAL CHECK (score BETWEEN 0 AND 100),
    CHECK (correct <= total),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (task_id) REFERENCES cognitive_tasks(id)
);

-- 6. Brain Twin : profil dynamique et historisé, avec incertitude
CREATE TABLE IF NOT EXISTS brain_twin_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id INTEGER,
    dimension TEXT NOT NULL CHECK (dimension IN ('WM', 'AT', 'PS', 'SP')),
    score REAL NOT NULL CHECK (score BETWEEN 0 AND 100),
    uncertainty REAL NOT NULL CHECK (uncertainty >= 0),
    ci_low REAL,
    ci_high REAL,
    n_tests INTEGER NOT NULL DEFAULT 1 CHECK (n_tests >= 1),
    is_projection INTEGER NOT NULL DEFAULT 0 CHECK (is_projection IN (0, 1)),
    horizon_sessions INTEGER CHECK (horizon_sessions IS NULL OR horizon_sessions >= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (is_projection = 0 OR horizon_sessions IS NOT NULL),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- 7. Feedback du coach (explicable, sans terme clinique)
CREATE TABLE IF NOT EXISTS coach_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    language TEXT NOT NULL DEFAULT 'fr',
    message TEXT NOT NULL,
    justification TEXT NOT NULL,
    target_dimension TEXT CHECK (target_dimension IN ('WM', 'AT', 'PS', 'SP')),
    clinical_term_detected INTEGER NOT NULL DEFAULT 0 CHECK (clinical_term_detected = 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

-- 8. Plans d'apprentissage adaptatifs et objectifs
CREATE TABLE IF NOT EXISTS learning_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('WM', 'AT', 'PS', 'SP')),
    exercise_name TEXT NOT NULL,
    difficulty_level INTEGER NOT NULL CHECK (difficulty_level BETWEEN 1 AND 5),
    rationale TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'done', 'skipped')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('WM', 'AT', 'PS', 'SP')),
    start_score REAL NOT NULL CHECK (start_score BETWEEN 0 AND 100),
    target_score REAL NOT NULL CHECK (target_score BETWEEN 0 AND 100),
    deadline TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'reached', 'abandoned')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Index
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, session_date);
CREATE INDEX IF NOT EXISTS idx_attempts_session ON task_attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_twin_user_dim ON brain_twin_history(user_id, dimension, created_at);

-- 9. Engagement / moral (EN, MO) : événements de partie, historique, auto-déclaration, e-mails
CREATE TABLE IF NOT EXISTS game_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    game TEXT NOT NULL,
    event TEXT NOT NULL CHECK (event IN ('started', 'completed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS engagement_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id INTEGER,
    en REAL NOT NULL,
    mo REAL NOT NULL,
    uncertainty REAL NOT NULL CHECK (uncertainty >= 0),
    n_obs INTEGER NOT NULL DEFAULT 1,
    candidate_state TEXT NOT NULL,
    state TEXT NOT NULL,
    signals_json TEXT,
    user_feedback TEXT CHECK (user_feedback IS NULL OR user_feedback IN ('confirmed', 'corrected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mood_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id INTEGER,
    mood_level INTEGER NOT NULL CHECK (mood_level BETWEEN 1 AND 4),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- Adresse e-mail stockée à part (opt-in séparé), supprimée au retrait du consentement
CREATE TABLE IF NOT EXISTS user_contacts (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    unsubscribe_token TEXT NOT NULL UNIQUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    state TEXT,
    subject TEXT,
    status TEXT NOT NULL CHECK (status IN ('sent', 'dry_run', 'failed')),
    sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_user ON game_events(user_id, id);
CREATE INDEX IF NOT EXISTS idx_engagement_user ON engagement_history(user_id, id);
CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(user_id, session_type, id);

-- Triggers : le score total est recalculé automatiquement (moyenne pondérée renormalisée)
CREATE TRIGGER IF NOT EXISTS trg_total_score_insert
AFTER INSERT ON dimension_scores
BEGIN
    UPDATE sessions
    SET total_score = (
        SELECT ROUND(SUM(score * weight) / SUM(weight), 2)
        FROM dimension_scores WHERE session_id = NEW.session_id
    )
    WHERE id = NEW.session_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_total_score_update
AFTER UPDATE OF score, weight ON dimension_scores
BEGIN
    UPDATE sessions
    SET total_score = (
        SELECT ROUND(SUM(score * weight) / SUM(weight), 2)
        FROM dimension_scores WHERE session_id = NEW.session_id
    )
    WHERE id = NEW.session_id;
END;

-- Vues pour le tableau de bord
CREATE VIEW IF NOT EXISTS v_radar_latest AS
SELECT b.user_id, b.dimension, b.score, b.uncertainty
FROM brain_twin_history b
WHERE b.is_projection = 0
  AND b.id = (
      SELECT MAX(id) FROM brain_twin_history
      WHERE user_id = b.user_id AND dimension = b.dimension AND is_projection = 0
  );

CREATE VIEW IF NOT EXISTS v_progress_curve AS
SELECT user_id, dimension, date(created_at) AS day, ROUND(AVG(score), 2) AS avg_score
FROM brain_twin_history
WHERE is_projection = 0
GROUP BY user_id, dimension, date(created_at);

CREATE VIEW IF NOT EXISTS v_collab_progress AS
SELECT user_id, date(session_date) AS day, ROUND(AVG(total_score), 2) AS avg_collab_score
FROM sessions
WHERE total_score IS NOT NULL
GROUP BY user_id, date(session_date);

CREATE VIEW IF NOT EXISTS v_goal_progress AS
SELECT g.id, g.user_id, g.dimension, g.target_score,
       r.score AS current_score,
       ROUND(100.0 * (r.score - g.start_score) / NULLIF(g.target_score - g.start_score, 0), 1) AS progress_pct
FROM goals g
LEFT JOIN v_radar_latest r ON r.user_id = g.user_id AND r.dimension = g.dimension
WHERE g.status = 'active';

-- Données de référence : catalogue des tâches
INSERT OR IGNORE INTO cognitive_tasks (dimension, task_name, definition, reference_time_s, known_biases) VALUES
('WM', 'reverse_digit_span', 'Retenir puis réécrire des chiffres à l''envers', 20, 'fatigue, bruit'),
('AT', 'target_detection', 'Cliquer uniquement sur la combinaison cible', 30, 'latence du clic, distractions'),
('PS', 'number_sequence', 'Trouver le terme suivant d''une suite logique', 45, 'culture mathématique'),
('SP', 'symbol_matching', 'Associer rapidement des symboles', 1.2, 'matériel, précipitation');
