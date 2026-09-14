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
    forced_checkout_count INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS disciplinary_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    strike_level INTEGER NOT NULL,
    reason TEXT NOT NULL,
    admin_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_profiles (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    game_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    citizen_id TEXT NOT NULL,
    hired_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS employee_departures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    departure_type TEXT NOT NULL,
    departed_at TEXT NOT NULL,
    admin_id INTEGER
);



CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    image_url TEXT NOT NULL,
    max_participants INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_participants (
    task_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted',
    accepted_at TEXT NOT NULL,
    completed_at TEXT,
    completed_by INTEGER,
    PRIMARY KEY (task_id, user_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS web_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    daily_hours TEXT NOT NULL,
    availability TEXT NOT NULL,
    previous_experience TEXT NOT NULL,
    difficult_customer TEXT NOT NULL,
    uniform_commitment TEXT NOT NULL,
    rules_agreement TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    token TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vacations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    days INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    reviewed_at TEXT,
    reviewed_by INTEGER,
    ended_at TEXT,
    ended_reason TEXT
);

CREATE TABLE IF NOT EXISTS weekly_activity (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    invoices INTEGER NOT NULL DEFAULT 0,
    work_seconds INTEGER NOT NULL DEFAULT 0,
    tasks INTEGER NOT NULL DEFAULT 0,
    points REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS weekly_activity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    week_no INTEGER NOT NULL,
    invoices INTEGER NOT NULL DEFAULT 0,
    work_seconds INTEGER NOT NULL DEFAULT 0,
    tasks INTEGER NOT NULL DEFAULT 0,
    points REAL NOT NULL DEFAULT 0,
    target_invoices INTEGER NOT NULL DEFAULT 15,
    archived_at TEXT NOT NULL,
    archived_by INTEGER
);
"""

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(CREATE_TABLES)
        # Migration آمنة للنسخ القديمة: لا تحذف أو تعيد إنشاء أي بيانات.
        cur = await db.execute("PRAGMA table_info(employees)")
        columns = {row[1] for row in await cur.fetchall()}
        if "forced_checkout_count" not in columns:
            await db.execute("ALTER TABLE employees ADD COLUMN forced_checkout_count INTEGER NOT NULL DEFAULT 0")

        # ترقية آمنة لنظام أدلة المهام بدون حذف أو تعديل البيانات القديمة.
        cur = await db.execute("PRAGMA table_info(task_participants)")
        task_columns = {row[1] for row in await cur.fetchall()}
        if "evidence_url" not in task_columns:
            await db.execute("ALTER TABLE task_participants ADD COLUMN evidence_url TEXT")
        if "evidence_at" not in task_columns:
            await db.execute("ALTER TABLE task_participants ADD COLUMN evidence_at TEXT")

        # ترقية آمنة لجدول طلبات الموقع بدون حذف أي طلبات قديمة.
        cur = await db.execute("PRAGMA table_info(web_applications)")
        app_columns = {row[1] for row in await cur.fetchall()}
        if "reviewed_at" not in app_columns:
            await db.execute("ALTER TABLE web_applications ADD COLUMN reviewed_at TEXT")
        if "reviewed_by" not in app_columns:
            await db.execute("ALTER TABLE web_applications ADD COLUMN reviewed_by INTEGER")

        # حالات الموظف ومنع إعادة التقديم بعد الفصل.
        cur = await db.execute("PRAGMA table_info(employee_profiles)")
        profile_columns = {row[1] for row in await cur.fetchall()}
        if "reapply_allowed" not in profile_columns:
            await db.execute("ALTER TABLE employee_profiles ADD COLUMN reapply_allowed INTEGER NOT NULL DEFAULT 1")
        if "status_updated_at" not in profile_columns:
            await db.execute("ALTER TABLE employee_profiles ADD COLUMN status_updated_at TEXT")

        await db.commit()


async def create_web_application(guild_id: int, user_id: int, answers: dict, token: str, created_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO web_applications "
            "(guild_id,user_id,reason,daily_hours,availability,previous_experience,"
            "difficult_customer,uniform_commitment,rules_agreement,status,token,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)",
            (
                guild_id,
                user_id,
                answers.get("reason", ""),
                answers.get("daily_hours", ""),
                answers.get("availability", ""),
                answers.get("previous_experience", ""),
                answers.get("difficult_customer", ""),
                answers.get("uniform_commitment", ""),
                answers.get("rules_agreement", ""),
                token,
                created_at,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_web_application_by_token(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,user_id,reason,daily_hours,availability,"
            "previous_experience,difficult_customer,uniform_commitment,"
            "rules_agreement,status,token,created_at "
            "FROM web_applications WHERE token=? LIMIT 1",
            (token,),
        )
        return await cur.fetchone()


async def get_web_application(app_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,user_id,reason,daily_hours,availability,"
            "previous_experience,difficult_customer,uniform_commitment,"
            "rules_agreement,status,token,created_at "
            "FROM web_applications WHERE id=? LIMIT 1",
            (app_id,),
        )
        return await cur.fetchone()


async def get_latest_web_application_for_user(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,user_id,reason,daily_hours,availability,"
            "previous_experience,difficult_customer,uniform_commitment,"
            "rules_agreement,status,token,created_at "
            "FROM web_applications WHERE guild_id=? AND user_id=? "
            "ORDER BY id DESC LIMIT 1",
            (guild_id, user_id),
        )
        return await cur.fetchone()


async def update_web_application_status(app_id: int, status: str, reviewed_at: str, reviewed_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE web_applications SET status=?, reviewed_at=?, reviewed_by=? WHERE id=?",
            (status, reviewed_at, reviewed_by, app_id),
        )
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
            "INSERT INTO weekly_activity (guild_id,user_id,work_seconds,points) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET work_seconds=work_seconds+excluded.work_seconds, points=points+excluded.points",
            (guild_id, user_id, worked_seconds, points_earned),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, points_earned, "ساعات العمل", check_out_at, forced_by),
        )
        await db.commit()

async def force_finish_attendance(session_id: int, guild_id: int, user_id: int, check_out_at: str, worked_seconds: int, points_earned: float, forced_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE attendance SET check_out_at=?, worked_seconds=?, points_earned=?, forced_by=? WHERE id=? AND check_out_at IS NULL",
            (check_out_at, worked_seconds, points_earned, forced_by, session_id),
        )
        await db.execute(
            "UPDATE employees SET points = points + ?, total_work_seconds = total_work_seconds + ?, forced_checkout_count = forced_checkout_count + 1 WHERE guild_id=? AND user_id=?",
            (points_earned, worked_seconds, guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO weekly_activity (guild_id,user_id,work_seconds,points) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET work_seconds=work_seconds+excluded.work_seconds, points=points+excluded.points",
            (guild_id, user_id, worked_seconds, points_earned),
        )
        cur = await db.execute(
            "SELECT forced_checkout_count FROM employees WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        forced_count = int(row[0]) if row else 0
        strike_level = max(0, min(3, forced_count - 1))
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, points_earned, "ساعات عمل - خروج إجباري", check_out_at, forced_by),
        )
        await db.commit()
    return forced_count, strike_level

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
            "INSERT INTO weekly_activity (guild_id,user_id,invoices,points) VALUES (?,?,1,1) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET invoices=invoices+1, points=points+1",
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
            "INSERT INTO weekly_activity (guild_id,user_id,tasks,points) VALUES (?,?,1,7) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET tasks=tasks+1, points=points+7",
            (guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id, user_id, amount, reason, created_at, admin_id) VALUES (?, ?, 7, ?, ?, ?)",
            (guild_id, user_id, f"مهمة: {reason}", created_at, admin_id),
        )
        await db.commit()

async def create_task(guild_id: int, channel_id: int, title: str, description: str, image_url: str, max_participants: int, created_by: int, created_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO tasks (guild_id,channel_id,title,description,image_url,max_participants,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (guild_id, channel_id, title, description, image_url, max_participants, created_by, created_at),
        )
        task_id = cur.lastrowid
        await db.commit()
        return int(task_id)

async def set_task_message(task_id: int, message_id: int, image_url: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if image_url:
            await db.execute("UPDATE tasks SET message_id=?, image_url=? WHERE id=?", (message_id, image_url, task_id))
        else:
            await db.execute("UPDATE tasks SET message_id=? WHERE id=?", (message_id, task_id))
        await db.commit()

async def get_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,channel_id,message_id,title,description,image_url,max_participants,status,created_by,created_at FROM tasks WHERE id=?",
            (task_id,),
        )
        return await cur.fetchone()

async def get_active_tasks(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,channel_id,message_id,title,description,image_url,max_participants,status,created_by,created_at FROM tasks WHERE guild_id=? AND status IN ('open','full') ORDER BY id DESC",
            (guild_id,),
        )
        return await cur.fetchall()

async def get_task_participant_count(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM task_participants WHERE task_id=?", (task_id,))
        row = await cur.fetchone()
        return int(row[0] or 0)

async def get_task_participants(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id,status,accepted_at,completed_at FROM task_participants WHERE task_id=? ORDER BY accepted_at ASC",
            (task_id,),
        )
        return await cur.fetchall()

async def accept_task(task_id: int, guild_id: int, user_id: int, accepted_at: str):
    # حجز المقعد بشكل ذري حتى لا يتجاوز العدد المحدد لو ضغط أكثر من شخص بنفس اللحظة.
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute("SELECT max_participants,status FROM tasks WHERE id=? AND guild_id=?", (task_id, guild_id))
        task = await cur.fetchone()
        if not task:
            await db.rollback(); return "not_found", 0, 0
        maximum, status = int(task[0]), task[1]
        if status != "open":
            await db.rollback(); return "closed", await _count_in_tx(db, task_id), maximum
        cur = await db.execute("SELECT 1 FROM task_participants WHERE task_id=? AND user_id=?", (task_id, user_id))
        if await cur.fetchone():
            count = await _count_in_tx(db, task_id)
            await db.rollback(); return "already", count, maximum
        count = await _count_in_tx(db, task_id)
        if count >= maximum:
            await db.execute("UPDATE tasks SET status='full' WHERE id=?", (task_id,))
            await db.commit(); return "full", count, maximum
        await db.execute(
            "INSERT INTO task_participants (task_id,guild_id,user_id,status,accepted_at) VALUES (?,?,?,?,?)",
            (task_id, guild_id, user_id, "accepted", accepted_at),
        )
        count += 1
        if count >= maximum:
            await db.execute("UPDATE tasks SET status='full' WHERE id=?", (task_id,))
        await db.commit()
        return "accepted", count, maximum

async def _count_in_tx(db, task_id: int):
    cur = await db.execute("SELECT COUNT(*) FROM task_participants WHERE task_id=?", (task_id,))
    row = await cur.fetchone()
    return int(row[0] or 0)

async def submit_task_evidence(task_id: int, guild_id: int, user_id: int, evidence_url: str, evidence_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT status FROM task_participants WHERE task_id=? AND guild_id=? AND user_id=?",
            (task_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            return "not_accepted"
        if row[0] == "completed":
            return "completed"
        await db.execute(
            "UPDATE task_participants SET evidence_url=?, evidence_at=? WHERE task_id=? AND guild_id=? AND user_id=?",
            (evidence_url, evidence_at, task_id, guild_id, user_id),
        )
        await db.commit()
        return "submitted"

async def get_pending_task_submissions(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT task_id,user_id FROM task_participants WHERE guild_id=? AND status='pending_review' AND evidence_url IS NOT NULL",
            (guild_id,),
        )
        return await cur.fetchall()

async def get_task_participant_evidence(task_id: int, guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT evidence_url,evidence_at,status FROM task_participants WHERE task_id=? AND guild_id=? AND user_id=?",
            (task_id, guild_id, user_id),
        )
        return await cur.fetchone()

async def approve_task_submission(task_id: int, guild_id: int, user_id: int, admin_id: int, approved_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute(
            "SELECT status,evidence_url FROM task_participants WHERE task_id=? AND guild_id=? AND user_id=?",
            (task_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            await db.rollback(); return "not_found"
        if row[0] == "completed":
            await db.rollback(); return "already_completed"
        if row[0] != "pending_review" or not row[1]:
            await db.rollback(); return "not_submitted"
        await db.execute(
            "UPDATE task_participants SET status='completed',completed_at=?,completed_by=? WHERE task_id=? AND guild_id=? AND user_id=?",
            (approved_at, admin_id, task_id, guild_id, user_id),
        )
        await db.execute(
            "UPDATE employees SET points=points+7,total_tasks=total_tasks+1 WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO weekly_activity (guild_id,user_id,tasks,points) VALUES (?,?,1,7) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET tasks=tasks+1, points=points+7",
            (guild_id, user_id),
        )
        await db.execute(
            "INSERT INTO point_transactions (guild_id,user_id,amount,reason,created_at,admin_id) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, 7, f"احتساب مهمة رقم {task_id}", approved_at, admin_id),
        )
        await db.commit()
        return "approved"

async def reject_task_submission(task_id: int, guild_id: int, user_id: int, rejected_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT status FROM task_participants WHERE task_id=? AND guild_id=? AND user_id=?",
            (task_id, guild_id, user_id),
        )
        row = await cur.fetchone()
        if not row:
            return "not_found"
        if row[0] == "completed":
            return "already_completed"
        if row[0] != "pending_review":
            return "not_submitted"
        # الرفض لا يلغي مقعد الموظف؛ يستطيع إعادة إرسال الدليل بعد التصحيح.
        await db.execute(
            "UPDATE task_participants SET status='accepted',evidence_url=NULL,evidence_at=NULL WHERE task_id=? AND guild_id=? AND user_id=?",
            (task_id, guild_id, user_id),
        )
        await db.commit()
        return "rejected"

async def complete_task_for_user(task_id: int, guild_id: int, user_id: int, completed_by: int, completed_at: str):
    # متوافق مع الاستدعاءات القديمة: الإكمال الإداري القديم أصبح اعتمادًا نهائيًا.
    return await approve_task_submission(task_id, guild_id, user_id, completed_by, completed_at)

async def close_task(task_id: int, guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tasks SET status='closed' WHERE id=? AND guild_id=?", (task_id, guild_id))
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

async def save_employee_profile(guild_id: int, user_id: int, game_name: str, phone_number: str, citizen_id: str, hired_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO employee_profiles (guild_id,user_id,game_name,phone_number,citizen_id,hired_at,status,reapply_allowed,status_updated_at) "
            "VALUES (?,?,?,?,?,?,'active',1,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET game_name=excluded.game_name, phone_number=excluded.phone_number, citizen_id=excluded.citizen_id, hired_at=excluded.hired_at, status='active', reapply_allowed=1, status_updated_at=excluded.status_updated_at",
            (guild_id,user_id,game_name,phone_number,citizen_id,hired_at,hired_at),
        )
        await db.commit()

async def get_employee_profile(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id,game_name,phone_number,citizen_id,hired_at,status FROM employee_profiles WHERE guild_id=? AND user_id=?", (guild_id,user_id))
        return await cur.fetchone()

async def search_employee_profiles(guild_id: int, query: str):
    q = f"%{query.strip()}%"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id,game_name,phone_number,citizen_id,hired_at,status FROM employee_profiles WHERE guild_id=? AND status='active' AND (game_name LIKE ? OR phone_number LIKE ? OR citizen_id LIKE ? OR CAST(user_id AS TEXT) LIKE ?) ORDER BY game_name LIMIT 25",
            (guild_id,q,q,q,q),
        )
        return await cur.fetchall()

async def list_employee_profiles(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id,game_name,phone_number,citizen_id,hired_at,status FROM employee_profiles WHERE guild_id=? AND status='active' ORDER BY game_name", (guild_id,))
        return await cur.fetchall()

async def remove_employee_profile(guild_id: int, user_id: int, departure_type: str, departed_at: str, admin_id=None):
    """ينهي حالة الموظف مع إبقاء سجله التاريخي بدل حذفه."""
    dep = (departure_type or "").strip()
    status = "fired" if dep == "فصل" else "resigned"
    reapply_allowed = 0 if status == "fired" else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE employee_profiles SET status=?, reapply_allowed=?, status_updated_at=? WHERE guild_id=? AND user_id=?",
            (status, reapply_allowed, departed_at, guild_id, user_id),
        )
        cur = await db.execute("SELECT changes()")
        changed = int((await cur.fetchone())[0] or 0)
        if not changed:
            await db.execute(
                "INSERT INTO employee_profiles "
                "(guild_id,user_id,game_name,phone_number,citizen_id,hired_at,status,reapply_allowed,status_updated_at) "
                "VALUES (?,?,?,'-','-','-',?,?,?)",
                (guild_id,user_id,f"Discord {user_id}",status,reapply_allowed,departed_at),
            )
        await db.execute(
            "INSERT INTO employee_departures (guild_id,user_id,departure_type,departed_at,admin_id) VALUES (?,?,?,?,?)",
            (guild_id,user_id,departure_type,departed_at,admin_id),
        )
        await db.commit()

async def add_disciplinary_action(guild_id: int, user_id: int, strike_level: int, reason: str, admin_id: int, created_at: str):
    level = max(1, min(3, int(strike_level)))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO disciplinary_actions (guild_id,user_id,strike_level,reason,admin_id,created_at) VALUES (?,?,?,?,?,?)",
            (guild_id, user_id, level, reason, admin_id, created_at),
        )
        await db.commit()

async def get_manual_strike_level(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COALESCE(MAX(strike_level),0) FROM disciplinary_actions WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return int(row[0] or 0) if row else 0

async def get_attendance_strike_level(guild_id: int, user_id: int) -> int:
    await ensure_employee(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT forced_checkout_count FROM employees WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        forced_count = int(row[0] or 0) if row else 0
        return max(0, min(3, forced_count - 1))


async def set_employee_status(guild_id: int, user_id: int, status: str, updated_at: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE employee_profiles SET status=?, status_updated_at=COALESCE(?, status_updated_at) WHERE guild_id=? AND user_id=?",
            (status, updated_at, guild_id, user_id),
        )
        await db.commit()

async def set_reapply_allowed(guild_id: int, user_id: int, allowed: bool, updated_at: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE employee_profiles SET reapply_allowed=?, status_updated_at=COALESCE(?, status_updated_at) WHERE guild_id=? AND user_id=?",
            (1 if allowed else 0, updated_at, guild_id, user_id),
        )
        # في حال كان الموظف القديم محذوفًا من النسخ السابقة، ننشئ سجل تحكم بسيط.
        cur = await db.execute("SELECT changes()")
        changed = (await cur.fetchone())[0]
        if not changed:
            await db.execute(
                "INSERT OR IGNORE INTO employee_profiles "
                "(guild_id,user_id,game_name,phone_number,citizen_id,hired_at,status,reapply_allowed,status_updated_at) "
                "VALUES (?,?,?,'-','-','-', 'fired', ?, ?)",
                (guild_id,user_id,f"Discord {user_id}",1 if allowed else 0,updated_at),
            )
        await db.commit()

async def can_user_apply(guild_id: int, user_id: int) -> tuple[bool, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT status,reapply_allowed FROM employee_profiles WHERE guild_id=? AND user_id=?",
            (guild_id,user_id),
        )
        row = await cur.fetchone()
        if row:
            status, allowed = row
            if status == "active":
                return False, "أنت موظف حاليًا ولا يمكنك تقديم طلب جديد."
            if status == "vacation":
                return False, "أنت في إجازة معتمدة ولا يمكنك تقديم طلب جديد."
            if status == "fired" and not int(allowed or 0):
                return False, "تم إنهاء عملك سابقًا ولا يمكنك إعادة التقديم إلا بعد سماح الإدارة."
        # توافق مع بيانات الفصل القديمة التي كانت تحذف ملف الموظف.
        cur = await db.execute(
            "SELECT departure_type FROM employee_departures WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (guild_id,user_id),
        )
        dep = await cur.fetchone()
        if dep and dep[0] == "فصل" and not row:
            return False, "تم إنهاء عملك سابقًا ولا يمكنك إعادة التقديم إلا بعد سماح الإدارة."
        if not row and not dep:
            cur = await db.execute("SELECT 1 FROM employees WHERE guild_id=? AND user_id=? LIMIT 1", (guild_id,user_id))
            if await cur.fetchone():
                return False, "أنت موظف حاليًا ولا يمكنك تقديم طلب جديد."
        return True, ""

async def create_vacation_request(guild_id: int, user_id: int, reason: str, days: int, requested_at: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM vacations WHERE guild_id=? AND user_id=? AND status IN ('pending','active') ORDER BY id DESC LIMIT 1",
            (guild_id,user_id),
        )
        if await cur.fetchone():
            return 0
        cur = await db.execute(
            "INSERT INTO vacations (guild_id,user_id,reason,days,status,requested_at) VALUES (?,?,?,?,'pending',?)",
            (guild_id,user_id,reason,int(days),requested_at),
        )
        await db.commit()
        return int(cur.lastrowid)

async def get_vacation(vacation_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,user_id,reason,days,status,requested_at,start_at,end_at,reviewed_at,reviewed_by,ended_at,ended_reason "
            "FROM vacations WHERE id=?",
            (vacation_id,),
        )
        return await cur.fetchone()

async def get_active_vacation(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,user_id,reason,days,status,requested_at,start_at,end_at,reviewed_at,reviewed_by,ended_at,ended_reason "
            "FROM vacations WHERE guild_id=? AND user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
            (guild_id,user_id),
        )
        return await cur.fetchone()

async def accept_vacation(vacation_id: int, start_at: str, end_at: str, reviewed_at: str, reviewed_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT guild_id,user_id FROM vacations WHERE id=? AND status='pending'", (vacation_id,))
        ids = await cur.fetchone()
        if not ids:
            return False
        guild_id,user_id = ids
        await db.execute(
            "UPDATE vacations SET status='active',start_at=?,end_at=?,reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'",
            (start_at,end_at,reviewed_at,reviewed_by,vacation_id),
        )
        await db.execute(
            "UPDATE employee_profiles SET status='vacation',status_updated_at=? WHERE guild_id=? AND user_id=?",
            (reviewed_at,guild_id,user_id),
        )
        cur = await db.execute("SELECT changes()")
        changed = int((await cur.fetchone())[0] or 0)
        if not changed:
            await db.execute(
                "INSERT INTO employee_profiles "
                "(guild_id,user_id,game_name,phone_number,citizen_id,hired_at,status,reapply_allowed,status_updated_at) "
                "VALUES (?,?,?,'-','-','-','vacation',1,?)",
                (guild_id,user_id,f"Discord {user_id}",reviewed_at),
            )
        await db.commit()
        return True

async def reject_vacation(vacation_id: int, reviewed_at: str, reviewed_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE vacations SET status='rejected',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'",
            (reviewed_at,reviewed_by,vacation_id),
        )
        await db.commit()

async def end_vacation(vacation_id: int, ended_at: str, reason: str = "expired"):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT guild_id,user_id FROM vacations WHERE id=? AND status='active'", (vacation_id,))
        row = await cur.fetchone()
        if not row:
            return None
        guild_id,user_id = row
        await db.execute(
            "UPDATE vacations SET status='ended',ended_at=?,ended_reason=? WHERE id=?",
            (ended_at,reason,vacation_id),
        )
        await db.execute(
            "UPDATE employee_profiles SET status='active',status_updated_at=? WHERE guild_id=? AND user_id=?",
            (ended_at,guild_id,user_id),
        )
        await db.commit()
        return guild_id,user_id

async def get_expired_vacations(now_iso: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id,guild_id,user_id,reason,days,status,requested_at,start_at,end_at,reviewed_at,reviewed_by,ended_at,ended_reason "
            "FROM vacations WHERE status='active' AND end_at IS NOT NULL AND end_at<=? ORDER BY end_at",
            (now_iso,),
        )
        return await cur.fetchall()

async def ensure_weekly_activity(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO weekly_activity (guild_id,user_id) VALUES (?,?)",
            (guild_id,user_id),
        )
        await db.commit()

async def get_weekly_activity(guild_id: int, user_id: int):
    await ensure_weekly_activity(guild_id,user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT invoices,work_seconds,tasks,points FROM weekly_activity WHERE guild_id=? AND user_id=?",
            (guild_id,user_id),
        )
        return await cur.fetchone()

async def get_all_weekly_activity(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        # الموظف يدخل في الجرد إذا كان ملفه Active/Vacation، أو لديه سجل إحصائيات ولم يسبق إنهاء خدمته.
        cur = await db.execute(
            """
            WITH roster AS (
                SELECT p.user_id, p.status
                FROM employee_profiles p
                WHERE p.guild_id=? AND p.status IN ('active','vacation')
                UNION
                SELECT e.user_id, 'active' AS status
                FROM employees e
                WHERE e.guild_id=?
                  AND NOT EXISTS (
                      SELECT 1 FROM employee_profiles p
                      WHERE p.guild_id=e.guild_id AND p.user_id=e.user_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM employee_departures d
                      WHERE d.guild_id=e.guild_id AND d.user_id=e.user_id
                  )
            )
            SELECT r.user_id,
                   COALESCE(w.invoices,0),
                   COALESCE(w.work_seconds,0),
                   COALESCE(w.tasks,0),
                   COALESCE(w.points,0),
                   r.status
            FROM roster r
            LEFT JOIN weekly_activity w ON w.guild_id=? AND w.user_id=r.user_id
            ORDER BY COALESCE(w.invoices,0) DESC, COALESCE(w.points,0) DESC, r.user_id
            """,
            (guild_id,guild_id,guild_id),
        )
        return await cur.fetchall()

async def reset_weekly_activity(guild_id: int, target_invoices: int, archived_at: str, archived_by: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COALESCE(MAX(week_no),0)+1 FROM weekly_activity_history WHERE guild_id=?", (guild_id,))
        week_no = int((await cur.fetchone())[0] or 1)
        cur = await db.execute(
            """
            WITH roster AS (
                SELECT p.user_id
                FROM employee_profiles p
                WHERE p.guild_id=? AND p.status IN ('active','vacation')
                UNION
                SELECT e.user_id
                FROM employees e
                WHERE e.guild_id=?
                  AND NOT EXISTS (SELECT 1 FROM employee_profiles p WHERE p.guild_id=e.guild_id AND p.user_id=e.user_id)
                  AND NOT EXISTS (SELECT 1 FROM employee_departures d WHERE d.guild_id=e.guild_id AND d.user_id=e.user_id)
            )
            SELECT r.user_id,
                   COALESCE(w.invoices,0),COALESCE(w.work_seconds,0),COALESCE(w.tasks,0),COALESCE(w.points,0)
            FROM roster r
            LEFT JOIN weekly_activity w ON w.guild_id=? AND w.user_id=r.user_id
            """,
            (guild_id,guild_id,guild_id),
        )
        rows = await cur.fetchall()
        for uid,invoices,work_seconds,tasks_count,points in rows:
            await db.execute(
                "INSERT INTO weekly_activity_history "
                "(guild_id,user_id,week_no,invoices,work_seconds,tasks,points,target_invoices,archived_at,archived_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (guild_id,uid,week_no,invoices,work_seconds,tasks_count,points,target_invoices,archived_at,archived_by),
            )
        await db.execute(
            "UPDATE weekly_activity SET invoices=0,work_seconds=0,tasks=0,points=0 WHERE guild_id=?",
            (guild_id,),
        )
        await db.commit()
        return week_no, rows

async def get_total_strikes(guild_id: int, user_id: int) -> int:
    """إجمالي الاسترايكات المسجلة تاريخيًا (اليدوية + الناتجة عن الخروج الإجباري)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM disciplinary_actions WHERE guild_id=? AND user_id=?",
            (guild_id,user_id),
        )
        manual_count = int((await cur.fetchone())[0] or 0)
        cur = await db.execute(
            "SELECT forced_checkout_count FROM employees WHERE guild_id=? AND user_id=?",
            (guild_id,user_id),
        )
        row = await cur.fetchone()
        forced_count = int(row[0] or 0) if row else 0
        attendance_strikes = max(0, forced_count - 1)
        return manual_count + attendance_strikes

async def get_excel_employee_rows(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            WITH roster AS (
                SELECT user_id FROM employee_profiles WHERE guild_id=?
                UNION
                SELECT user_id FROM employees WHERE guild_id=?
                UNION
                SELECT user_id FROM employee_departures WHERE guild_id=?
            ), latest_departure AS (
                SELECT d.user_id,d.departure_type
                FROM employee_departures d
                JOIN (
                    SELECT user_id,MAX(id) AS max_id
                    FROM employee_departures WHERE guild_id=? GROUP BY user_id
                ) x ON x.max_id=d.id
            )
            SELECT r.user_id,
                   COALESCE(p.game_name, 'Discord ' || r.user_id),
                   COALESCE(p.phone_number,'-'),
                   COALESCE(p.citizen_id,'-'),
                   COALESCE(p.hired_at,'-'),
                   COALESCE(p.status, CASE WHEN ld.departure_type='فصل' THEN 'fired' WHEN ld.departure_type IS NOT NULL THEN 'resigned' ELSE 'active' END),
                   COALESCE(p.reapply_allowed, CASE WHEN ld.departure_type='فصل' THEN 0 ELSE 1 END),
                   COALESCE(e.total_invoices,0),COALESCE(e.total_work_seconds,0),COALESCE(e.total_tasks,0),COALESCE(e.points,0),
                   COALESCE(w.invoices,0),COALESCE(w.work_seconds,0),COALESCE(w.tasks,0),COALESCE(w.points,0),
                   v.days,v.start_at,v.end_at
            FROM roster r
            LEFT JOIN employee_profiles p ON p.guild_id=? AND p.user_id=r.user_id
            LEFT JOIN latest_departure ld ON ld.user_id=r.user_id
            LEFT JOIN employees e ON e.guild_id=? AND e.user_id=r.user_id
            LEFT JOIN weekly_activity w ON w.guild_id=? AND w.user_id=r.user_id
            LEFT JOIN vacations v ON v.id=(
                SELECT vv.id FROM vacations vv WHERE vv.guild_id=? AND vv.user_id=r.user_id
                ORDER BY vv.id DESC LIMIT 1
            )
            ORDER BY CASE COALESCE(p.status, CASE WHEN ld.departure_type='فصل' THEN 'fired' WHEN ld.departure_type IS NOT NULL THEN 'resigned' ELSE 'active' END)
                     WHEN 'active' THEN 0 WHEN 'vacation' THEN 1 WHEN 'fired' THEN 2 ELSE 3 END,
                     COALESCE(p.game_name, 'Discord ' || r.user_id)
            """,
            (guild_id,guild_id,guild_id,guild_id,guild_id,guild_id,guild_id,guild_id),
        )
        return await cur.fetchall()

async def get_pending_vacations(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM vacations WHERE guild_id=? AND status='pending' ORDER BY id",
            (guild_id,),
        )
        return await cur.fetchall()
