import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timedelta

DB_PATH = "vacaciones.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vacations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee TEXT NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pendiente','aprobada','rechazada')),
                note TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                approved_by TEXT,
                approved_at TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_vacations_emp_dates
            ON vacations(employee, start_date, end_date, status);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
        """)

def ensure_employees(seed_names=None):
    if not seed_names:
        return
    with get_conn() as conn:
        for n in seed_names:
            try:
                conn.execute("INSERT OR IGNORE INTO employees(name, active) VALUES (?,1);", (n,))
            except Exception:
                pass

def list_employees(active_only=True):
    sql = "SELECT name FROM employees" + (" WHERE active=1" if active_only else "")
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return [r["name"] for r in rows]

def add_employee(name: str):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO employees(name, active) VALUES (?,1);", (name,))

def set_employee_active(name: str, active: bool):
    with get_conn() as conn:
        conn.execute("UPDATE employees SET active=? WHERE name=?;", (1 if active else 0, name))

def daterange(d0: date, d1: date):
    step = timedelta(days=1)
    cur = d0
    while cur <= d1:
        yield cur
        cur += step

def has_overlap_for_employee(employee: str, start_date: date, end_date: date, include_pending=True):
    with get_conn() as conn:
        statuses = ("'aprobada','pendiente'") if include_pending else ("'aprobada'")
        sql = f"""
            SELECT COUNT(*) as cnt
            FROM vacations
            WHERE employee=? AND status IN ({statuses})
              AND NOT (end_date < ? OR start_date > ?)
        """
        row = conn.execute(sql, (employee, start_date, end_date)).fetchone()
        return (row["cnt"] or 0) > 0

def create_request(employee: str, start_date: date, end_date: date, note: str | None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO vacations(employee, start_date, end_date, status, note)
            VALUES (?, ?, ?, 'pendiente', ?);
        """, (employee, start_date, end_date, note))

def update_status(vacation_id: int, new_status: str, approver: str | None):
    now = datetime.utcnow()
    with get_conn() as conn:
        conn.execute("""
            UPDATE vacations
            SET status=?, approved_by=?, approved_at=?
            WHERE id=?;
        """, (new_status, approver, now if new_status in ("aprobada","rechazada") else None, vacation_id))

def delete_request(vacation_id: int, employee: str | None = None):
    # If employee provided, only delete own pending requests
    with get_conn() as conn:
        if employee:
            conn.execute("DELETE FROM vacations WHERE id=? AND employee=? AND status='pendiente';", (vacation_id, employee))
        else:
            conn.execute("DELETE FROM vacations WHERE id=?;", (vacation_id,))

def list_requests(year: int | None = None, month: int | None = None, status: str | None = None):
    sql = "SELECT * FROM vacations WHERE 1=1"
    params = []
    if year and month:
        sql += " AND strftime('%Y', start_date)=? AND (strftime('%m', start_date)=? OR strftime('%m', end_date)=?)"
        params.extend([f"{year:04d}", f"{month:02d}", f"{month:02d}"])
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY start_date ASC;"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]

def get_calendar_matrix(year: int, month: int):
    # Build: {employee: {day: 'aprobada'|'pendiente'|'rechazada'|None}}
    from calendar import monthrange
    employees = list_employees(active_only=True)
    days = monthrange(year, month)[1]
    matrix = {emp: {d: None for d in range(1, days+1)} for emp in employees}

    # Load requests overlapping month
    with get_conn() as conn:
        # All rows that touch the month
        start = date(year, month, 1)
        end = date(year, month, days)
        rows = conn.execute("""
            SELECT * FROM vacations
            WHERE NOT (end_date < ? OR start_date > ?)
        """, (start, end)).fetchall()

    for r in rows:
        emp = r["employee"]
        s = datetime.strptime(r["start_date"], "%Y-%m-%d").date() if isinstance(r["start_date"], str) else r["start_date"]
        e = datetime.strptime(r["end_date"], "%Y-%m-%d").date() if isinstance(r["end_date"], str) else r["end_date"]
        status = r["status"]
        cur_s = max(s, start)
        cur_e = min(e, end)
        for d in daterange(cur_s, cur_e):
            if emp in matrix:
                matrix[emp][d.day] = status
    return matrix, days