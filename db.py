import aiosqlite
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = "workout.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Тренировочные записи
        await db.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            exercise TEXT NOT NULL,
            reps INTEGER NOT NULL,
            weight REAL,
            ts TEXT NOT NULL
        );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entries_user_ts ON entries(user_id, ts);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_entries_exercise_ts ON entries(exercise, ts);")

        # Параметры тела (рост/вес)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS body_params (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            height_cm REAL,
            weight_kg REAL,
            ts TEXT NOT NULL
        );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_body_user_ts ON body_params(user_id, ts);")

        await db.commit()


async def add_entry(
        user_id: int,
        exercise: str,
        reps: int,
        weight: Optional[float] = None,
        ts: Optional[datetime] = None
):
    if ts is None:
        ts = datetime.utcnow()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO entries (user_id, exercise, reps, weight, ts) VALUES (?,?,?,?,?)",
            (user_id, exercise.strip().lower(), int(reps),
             float(weight) if weight is not None else None, ts.isoformat())
        )
        await db.commit()


async def recent_summary(user_id: int, exercise: Optional[str] = None, days: int = 7):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if exercise:
            sql = """
            SELECT exercise, SUM(reps) AS total_reps, COUNT(*) AS sets
            FROM entries
            WHERE user_id=? AND exercise=? AND ts>=?
            GROUP BY exercise
            ORDER BY total_reps DESC
            """
            params = (user_id, exercise.strip().lower(), since)
        else:
            sql = """
            SELECT exercise, SUM(reps) AS total_reps, COUNT(*) AS sets
            FROM entries
            WHERE user_id=? AND ts>=?
            GROUP BY exercise
            ORDER BY total_reps DESC
            """
            params = (user_id, since)
        async with db.execute(sql, params) as cur:
            return await cur.fetchall()


async def last_n_entries(user_id: int, exercise: str, n: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT ts, reps, weight FROM entries WHERE user_id=? AND exercise=? ORDER BY ts DESC LIMIT ?",
                (user_id, exercise.strip().lower(), n)
        ) as cur:
            return await cur.fetchall()


async def timeseries_daily(user_id: int, exercise: Optional[str], days: int = 30):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        if exercise:
            sql = """
            SELECT substr(ts, 1, 10) AS d,
                   SUM(reps) AS total_reps,
                   SUM(CASE WHEN weight IS NOT NULL THEN reps*weight ELSE 0 END) AS total_volume,
                   COUNT(*) AS sets
            FROM entries
            WHERE user_id = ? AND exercise = ? AND ts >= ?
            GROUP BY d
            ORDER BY d
            """
            params = (user_id, exercise.strip().lower(), since)
        else:
            sql = """
            SELECT substr(ts, 1, 10) AS d,
                   SUM(reps) AS total_reps,
                   SUM(CASE WHEN weight IS NOT NULL THEN reps*weight ELSE 0 END) AS total_volume,
                   COUNT(*) AS sets
            FROM entries
            WHERE user_id = ? AND ts >= ?
            GROUP BY d
            ORDER BY d
            """
            params = (user_id, since)
        async with db.execute(sql, params) as cur:
            return await cur.fetchall()


# ===== Параметры тела =====

async def add_body_params(
        user_id: int,
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        ts: Optional[datetime] = None
):
    """Сохранить замер роста/веса; допускает None для одного из полей."""
    if ts is None:
        ts = datetime.utcnow()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO body_params (user_id, height_cm, weight_kg, ts) VALUES (?,?,?,?)",
            (user_id,
             float(height_cm) if height_cm is not None else None,
             float(weight_kg) if weight_kg is not None else None,
             ts.isoformat())
        )
        await db.commit()


async def last_body_params(user_id: int):
    """Последний замер роста/веса пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT height_cm, weight_kg, ts FROM body_params WHERE user_id=? ORDER BY ts DESC LIMIT 1",
                (user_id,)
        ) as cur:
            return await cur.fetchone()


# db.py
async def last_n_body_params(user_id: int, n: int = 10):
    """Последние n замеров роста/веса."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT ts, height_cm, weight_kg FROM body_params WHERE user_id=? ORDER BY ts DESC LIMIT ?",
                (user_id, n)
        ) as cur:
            return await cur.fetchall()
