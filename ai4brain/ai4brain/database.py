import sqlite3
from pathlib import Path
DB_PATH = Path(__file__).parent / 'data' / 'ai4brain.db'

class _ClosingConnection(sqlite3.Connection):
    """Keep sqlite's transaction context manager and close after its scope."""
    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, factory=_ClosingConnection)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys = ON')
    return c

def init_db():
    with get_connection() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            name TEXT NOT NULL, 
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER NOT NULL, 
            dimension TEXT NOT NULL,
            score REAL NOT NULL CHECK(score BETWEEN 0 AND 100), 
            difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 10),
            response_time REAL NOT NULL DEFAULT 0, 
            old_level INTEGER NOT NULL, 
            new_level INTEGER NOT NULL, 
            rating REAL NOT NULL, -- Suivi du rating Elo après l'exercice
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        
        CREATE TABLE IF NOT EXISTS learning_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            version_id TEXT NOT NULL, 
            user_id INTEGER NOT NULL, 
            week_start TEXT NOT NULL,
            dimension TEXT NOT NULL, 
            target_score REAL NOT NULL, 
            current_score REAL NOT NULL, 
            gap REAL NOT NULL, 
            priority REAL NOT NULL,
            sessions INTEGER NOT NULL, 
            session_minutes INTEGER NOT NULL, 
            note TEXT NOT NULL, 
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, 
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        ''')
        if c.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0:
            c.execute('INSERT INTO users(name) VALUES (?)', ('Utilisateur démo',))

def create_user(name):
    with get_connection() as c: 
        c.execute('INSERT INTO users(name) VALUES (?)', (name,))

def list_users():
    with get_connection() as c: 
        return [dict(r) for r in c.execute('SELECT id, name FROM users ORDER BY id')]

def add_score(user_id, dimension, score, difficulty, response_time, old_level, new_level, rating, reason):
    with get_connection() as c:
        c.execute('''
            INSERT INTO scores(user_id, dimension, score, difficulty, response_time, old_level, new_level, rating, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, dimension, score, difficulty, response_time, old_level, new_level, rating, reason))

def get_scores(user_id, dimension=None):
    with get_connection() as c:
        if dimension: 
            rows = c.execute('SELECT * FROM scores WHERE user_id=? AND dimension=? ORDER BY id', (user_id, dimension)).fetchall()
        else: 
            rows = c.execute('SELECT * FROM scores WHERE user_id=? ORDER BY id', (user_id,)).fetchall()
        return [dict(r) for r in rows]

def get_latest_scores(user_id):
    with get_connection() as c:
        rows = c.execute('''
            SELECT s.dimension, s.score FROM scores s JOIN
            (SELECT dimension, MAX(id) max_id FROM scores WHERE user_id=? GROUP BY dimension) x ON x.max_id=s.id
        ''', (user_id,)).fetchall()
        return {r['dimension']: r['score'] for r in rows}

def save_plan(user_id, plan_rows, week_start):
    import uuid
    version = uuid.uuid4().hex[:10]
    with get_connection() as c:
        c.execute("UPDATE learning_plans SET status='superseded' WHERE user_id=? AND status='active'", (user_id,))
        for r in plan_rows:
            c.execute('''
                INSERT INTO learning_plans(version_id, user_id, week_start, dimension, target_score, current_score, gap, priority, sessions, session_minutes, note, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            ''', (version, user_id, week_start.isoformat(), r['dimension'], r['target_score'], r['current_score'], r['gap'], r['priority'], r['sessions'], r['session_minutes'], r['note']))

def get_active_plan(user_id):
    with get_connection() as c: 
        return [dict(r) for r in c.execute("SELECT * FROM learning_plans WHERE user_id=? AND status='active' ORDER BY priority DESC", (user_id,))]

def get_plan_history(user_id):
    with get_connection() as c: 
        return [dict(r) for r in c.execute('SELECT version_id, week_start, dimension, target_score, current_score, gap, priority, sessions, status, created_at FROM learning_plans WHERE user_id=? ORDER BY id DESC', (user_id,))]
