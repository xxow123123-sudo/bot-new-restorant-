import aiosqlite
from config import DB_PATH

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS settings (
    guild_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS employees (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    points REAL NOT NULL DEFAULT 0,
    total_work_seconds INTEGER NOT NULL DEFAULT 0,
    total_invoices INTEGER NOT NULL DEFAULT 0,
    total_tasks INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    check_in_at TEXT NOT NULL,
    check_in_image TEXT NOT NULL,
    check_out_at TEXT,
    check_out_image TEXT,
    worked_seconds INTEGER,
    points_earned REAL DEFAULT 0,
    forced_by INTEGER
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    image_url TEXT NOT NULL,
    points_earned REAL NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS point_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    admin_id INTEGER
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES)
        await db.commit()

async def set_setting(guild_id: int, key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, value),
        )
        await db.commit()

async def get_setting(guild_id: int, key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        )
        row = await cur.fetchone()
        return row[0] if row else None

async def get_all_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT key, value FROM settings WHERE guild_id=? ORDER BY key",
            (guild_id,),
        )
        return dict(await cur.fetchall())

async def ensure_employee(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO employees (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        await db.commit()

async def get_points(guild_id: int, user_id: int) -> float:
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT points FROM employees WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return float(row[0]) if row else 0.0

async def add_points(guild_id: int, user_id: int, amount: float, reason: str, created_at: str, admin_id=None):
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE employees SET points = points + ? WHERE guild_id=? AND user_id=?",
            (amount, guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, amount, reason, created_at, admin_id),
        )
        await db.commit()

async def set_points(guild_id: int, user_id: int, value: float, reason: str, created_at: str, admin_id=None):
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT points FROM employees WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        old_points = float(row[0]) if row else 0.0
        difference = float(value) - old_points
        await db.execute(
            "UPDATE employees SET points=? WHERE guild_id=? AND user_id=?",
            (value, guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, difference, reason, created_at, admin_id),
        )
        await db.commit()

async def reset_all_points(guild_id: int, created_at: str, admin_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, points FROM employees WHERE guild_id=?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        for user_id, points in rows:
            if float(points) != 0:
                await db.execute(
                    "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (guild_id, user_id, -float(points), "تصفير أسبوعي/إداري", created_at, admin_id),
                )
        await db.execute("UPDATE employees SET points=0 WHERE guild_id=?", (guild_id,))
        await db.commit()
        return len(rows)

async def get_active_attendance(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, check_in_at, check_in_image FROM attendance "
            "WHERE guild_id=? AND user_id=? AND check_out_at IS NULL ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
        return await cur.fetchone()

async def get_all_active_attendance(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, check_in_at FROM attendance "
            "WHERE guild_id=? AND check_out_at IS NULL ORDER BY check_in_at ASC",
            (guild_id,),
        )
        return await cur.fetchall()

async def start_attendance(guild_id: int, user_id: int, check_in_at: str, image_url: str):
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO attendance (guild_id, user_id, check_in_at, check_in_image) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, check_in_at, image_url),
        )
        await db.commit()

async def finish_attendance(session_id: int, guild_id: int, user_id: int, check_out_at: str, image_url: str, worked_seconds: int, points_earned: float, forced_by=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE attendance SET check_out_at=?, check_out_image=?, worked_seconds=?, points_earned=?, forced_by=? "
            "WHERE id=? AND check_out_at IS NULL",
            (check_out_at, image_url, worked_seconds, points_earned, forced_by, session_id),
        )
        await db.execute(
            "UPDATE employees SET points = points + ?, total_work_seconds = total_work_seconds + ? "
            "WHERE guild_id=? AND user_id=?",
            (points_earned, worked_seconds, guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, points_earned, "ساعات العمل", check_out_at, forced_by),
        )
        await db.commit()

async def force_finish_attendance(session_id: int, guild_id: int, user_id: int, check_out_at: str, worked_seconds: int, points_earned: float, forced_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE attendance SET check_out_at=?, worked_seconds=?, points_earned=?, forced_by=? "
            "WHERE id=? AND check_out_at IS NULL",
            (check_out_at, worked_seconds, points_earned, forced_by, session_id),
        )
        await db.execute(
            "UPDATE employees SET points = points + ?, total_work_seconds = total_work_seconds + ? "
            "WHERE guild_id=? AND user_id=?",
            (points_earned, worked_seconds, guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, points_earned, "ساعات عمل - خروج إجباري", check_out_at, forced_by),
        )
        await db.commit()

async def add_invoice(guild_id: int, user_id: int, created_at: str, image_url: str):
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO invoices (guild_id, user_id, created_at, image_url, points_earned) VALUES (?, ?, ?, ?, 1)",
            (guild_id, user_id, created_at, image_url),
        )
        await db.execute(
            "UPDATE employees SET points = points + 1, total_invoices = total_invoices + 1 WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at) VALUES (?, ?, 1, ?, ?)",
            (guild_id, user_id, "فاتورة", created_at),
        )
        await db.commit()

async def add_task(guild_id: int, user_id: int, created_at: str, admin_id=None, reason: str = "مهمة"):
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE employees SET points = points + 7, total_tasks = total_tasks + 1 WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, 7, ?, ?, ?)",
            (guild_id, user_id, f"مهمة: {reason}", created_at, admin_id),
        )
        await db.commit()

async def get_all_employee_stats(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, points, total_work_seconds, total_invoices, total_tasks "
            "FROM employees WHERE guild_id=? ORDER BY points DESC, user_id ASC",
            (guild_id,),
        )
        return await cur.fetchall()

async def get_employee_stats(guild_id: int, user_id: int):
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT points, total_work_seconds, total_invoices, total_tasks "
            "FROM employees WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        return await cur.fetchone()