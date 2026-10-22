"""HR rules for the company portal: employee records, schedules, attendance requests, leave and holidays.

No Streamlit code in this file, so it can be tested on its own. Uses the same database and accounts as the
rest of the portal.

Rules:
  Each employee has a permanent employee ID (for example 2026-0001). It is never reused.
  An employee record can be linked to a portal account (username). Attendance and payroll use that link.
  Salary is stored encrypted when SALARY_KEY is set. Bank details are stored only when the owner turns
  the "store bank details" setting on, and are encrypted the same way.
  A schedule is one row per employee per date: start, end, break minutes, or a rest day.
  Attendance corrections and overtime are requests. A supervisor of the branch, HR, a manager or the
  owner approves or rejects them. An approved correction changes the attendance record.
  Leave is requested and approved the same way. Approved leave counts against the year's balance.
"""
import base64
import hashlib
import os
import re
import secrets
from datetime import date, datetime, timedelta

import pandas as pd

import att_logic as a
import kpi_logic as k

APPROVER_ROLES = ("supervisor", "hr", "manager", "owner")
HR_ROLES = ("hr", "owner")
PAY_ROLES = ("payroll", "owner")
EMPLOYMENT_STATUSES = ("Probationary", "Regular", "Contractual", "Project-based", "Resigned", "Terminated")
CIVIL_STATUSES = ("Single", "Married", "Widowed", "Separated")
RATE_TYPES = ("monthly", "daily")
REQUEST_KINDS = ("Missing time in or out", "Wrong time", "Overtime")
DEFAULT_LEAVE_TYPES = [
    # code, name, paid, days per year
    ("SIL", "Service Incentive Leave", 1, 5),
    ("VL", "Vacation leave", 1, 0),
    ("SL", "Sick leave", 1, 0),
    ("ML", "Maternity leave", 1, 105),
    ("PL", "Paternity leave", 1, 7),
    ("SPL", "Solo parent leave", 1, 7),
    ("LWOP", "Leave without pay", 0, 0),
]


def _schema(is_pg):
    num = "DOUBLE PRECISION" if is_pg else "REAL"
    return [
        f"""CREATE TABLE IF NOT EXISTS employees (
            emp_id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            full_name TEXT NOT NULL,
            branch_code TEXT,
            position TEXT,
            employment_status TEXT,
            civil_status TEXT,
            date_hired TEXT,
            rate_type TEXT NOT NULL DEFAULT 'monthly',
            rate_enc TEXT,
            bank_enc TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT, updated_at TEXT, updated_by TEXT)""",
        """CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, updated_by TEXT)""",
        """CREATE TABLE IF NOT EXISTS schedules (
            username TEXT NOT NULL, work_date TEXT NOT NULL,
            shift_start TEXT, shift_end TEXT, break_minutes INTEGER NOT NULL DEFAULT 60,
            rest_day INTEGER NOT NULL DEFAULT 0, updated_by TEXT, updated_at TEXT,
            PRIMARY KEY (username, work_date))""",
        f"""CREATE TABLE IF NOT EXISTS att_requests (
            id TEXT PRIMARY KEY, username TEXT NOT NULL, work_date TEXT NOT NULL, kind TEXT NOT NULL,
            req_in TEXT, req_out TEXT, ot_hours {num}, reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending', created_at TEXT,
            reviewed_by TEXT, reviewed_at TEXT, review_note TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS leave_types (
            code TEXT PRIMARY KEY, name TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 1,
            days_per_year {num} NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)""",
        f"""CREATE TABLE IF NOT EXISTS leave_balances (
            username TEXT NOT NULL, year INTEGER NOT NULL, code TEXT NOT NULL, entitled {num} NOT NULL,
            PRIMARY KEY (username, year, code))""",
        f"""CREATE TABLE IF NOT EXISTS leave_requests (
            id TEXT PRIMARY KEY, username TEXT NOT NULL, code TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, days {num} NOT NULL, reason TEXT,
            status TEXT NOT NULL DEFAULT 'Pending', created_at TEXT,
            reviewed_by TEXT, reviewed_at TEXT, review_note TEXT)""",
        """CREATE TABLE IF NOT EXISTS holidays (
            hdate TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('regular','special')))""",
        "CREATE INDEX IF NOT EXISTS idx_sched_date ON schedules (work_date)",
    ]


def init_hr(db):
    db.run([(s, ()) for s in _schema(db.is_pg)])
    if db.one("SELECT COUNT(*) FROM leave_types")[0] == 0:
        db.insert_many("leave_types", ["code", "name", "paid", "days_per_year"],
                       [list(x) for x in DEFAULT_LEAVE_TYPES])


# ---------------------------------------------------------------- settings
def get_setting(db, key, default=None):
    row = db.one("SELECT value FROM settings WHERE key = ?", (key,))
    return default if not row or row[0] is None else row[0]


def set_setting(db, key, value, by):
    stamp = k.now()
    db.run([("DELETE FROM settings WHERE key = ?", (key,)),
            ("INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?,?,?,?)", (key, str(value), stamp, by))])
    k.log(db, by, "set_setting", key)


def store_bank_details(db):
    return get_setting(db, "store_bank_details", "0") == "1"


# ---------------------------------------------------------------- encryption of salary and bank fields
# The key comes from the SALARY_KEY secret, which the company keeps in its hosting account.
# Without it, values are stored as plain text and the Admin page shows a warning.
def _fernet():
    key = os.environ.get("SALARY_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet
    raw = hashlib.sha256(key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encryption_on():
    return _fernet() is not None


def _enc(value):
    if value is None or value == "":
        return None
    f = _fernet()
    text = str(value)
    return ("enc:" + f.encrypt(text.encode()).decode()) if f else ("plain:" + text)


def _dec(value):
    if not isinstance(value, str) or value == "":
        return None
    if value.startswith("plain:"):
        return value[6:]
    if value.startswith("enc:"):
        f = _fernet()
        if not f:
            raise ValueError("Salary data is encrypted but SALARY_KEY is not set.")
        return f.decrypt(value[4:].encode()).decode()
    return value


# ---------------------------------------------------------------- employees
def next_emp_id(db, year=None):
    year = year or date.today().year
    ids = db.query("SELECT emp_id FROM employees WHERE emp_id LIKE ?", (f"{year}-%",))["emp_id"]
    nums = [int(x.split("-")[1]) for x in ids if re.fullmatch(r"\d{4}-\d{4}", x)]
    return f"{year}-{(max(nums) + 1 if nums else 1):04d}"


def save_employee(db, by, emp_id=None, full_name="", username=None, branch_code=None, position=None,
                  employment_status="Probationary", civil_status="Single", date_hired=None,
                  rate_type="monthly", rate=None, bank=None):
    """Create (no emp_id, or an emp_id not yet used) or update an employee. Returns the employee ID.
    rate=None keeps the stored rate. bank is stored only when the bank setting is on."""
    full_name = (full_name or "").strip()
    if not full_name:
        raise ValueError("Enter the employee's full name.")
    if rate_type not in RATE_TYPES:
        raise ValueError("Rate type must be monthly or daily.")
    if employment_status and employment_status not in EMPLOYMENT_STATUSES:
        raise ValueError("Unknown employment status.")
    if civil_status and civil_status not in CIVIL_STATUSES:
        raise ValueError("Unknown civil status.")
    username = (username or "").strip().lower() or None
    if username and not db.one("SELECT COUNT(*) FROM users WHERE username = ?", (username,))[0]:
        raise ValueError(f"No portal account named {username}.")
    branch_code = (branch_code or "").strip() or None
    if branch_code and not db.one("SELECT COUNT(*) FROM branches WHERE branch_code = ?", (branch_code,))[0]:
        raise ValueError(f"{branch_code} is not in the branch list.")
    if rate is not None and rate != "":
        rate = float(rate)
        if rate < 0:
            raise ValueError("The rate cannot be negative.")
    emp_id = (emp_id or "").strip()
    if emp_id and not re.fullmatch(r"[A-Za-z0-9-]{3,20}", emp_id):
        raise ValueError("Employee ID: 3 to 20 letters, numbers or dashes.")
    exists = bool(emp_id) and db.one("SELECT COUNT(*) FROM employees WHERE emp_id = ?", (emp_id,))[0] > 0
    if username:
        other = db.one("SELECT emp_id FROM employees WHERE username = ? AND emp_id <> ?", (username, emp_id or ""))
        if other:
            raise ValueError(f"{username} is already linked to employee {other[0]}.")
    stamp = k.now()
    bank_value = _enc(bank) if (bank and store_bank_details(db)) else None
    if exists:
        sets = ["full_name=?", "username=?", "branch_code=?", "position=?", "employment_status=?",
                "civil_status=?", "date_hired=?", "rate_type=?", "updated_at=?", "updated_by=?"]
        vals = [full_name, username, branch_code, position, employment_status, civil_status,
                str(date_hired) if date_hired else None, rate_type, stamp, by]
        if rate is not None and rate != "":
            sets.append("rate_enc=?"); vals.append(_enc(rate))
        if bank_value:
            sets.append("bank_enc=?"); vals.append(bank_value)
        db.run([(f"UPDATE employees SET {', '.join(sets)} WHERE emp_id = ?", vals + [emp_id])])
        k.log(db, by, "update_employee", emp_id)
    else:
        emp_id = emp_id or next_emp_id(db)
        db.run([("""INSERT INTO employees (emp_id, username, full_name, branch_code, position, employment_status,
                    civil_status, date_hired, rate_type, rate_enc, bank_enc, active, created_at, updated_at, updated_by)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
                 (emp_id, username, full_name, branch_code, position, employment_status, civil_status,
                  str(date_hired) if date_hired else None, rate_type,
                  _enc(rate) if rate not in (None, "") else None, bank_value, stamp, stamp, by))])
        k.log(db, by, "create_employee", emp_id)
    return emp_id


def set_pay(db, emp_id, rate_type, rate, by, bank=None):
    """Payroll action: set the rate (and bank details when that setting is on) without touching the rest."""
    if rate_type not in RATE_TYPES:
        raise ValueError("Rate type must be monthly or daily.")
    rate = float(str(rate).replace(",", ""))
    if rate < 0:
        raise ValueError("The rate cannot be negative.")
    if not db.one("SELECT COUNT(*) FROM employees WHERE emp_id = ?", (emp_id,))[0]:
        raise ValueError(f"Employee {emp_id} not found.")
    stmts = [("UPDATE employees SET rate_type = ?, rate_enc = ?, updated_at = ?, updated_by = ? WHERE emp_id = ?",
              (rate_type, _enc(rate), k.now(), by, emp_id))]
    if bank and store_bank_details(db):
        stmts.append(("UPDATE employees SET bank_enc = ? WHERE emp_id = ?", (_enc(bank), emp_id)))
    db.run(stmts)
    k.log(db, by, "set_pay", emp_id)


def bulk_rates(db, table, by):
    """Payroll upload: Employee ID, Rate Type, Rate (and Bank when stored)."""
    cols = {str(c).strip().lower(): c for c in table.columns}
    for need in ("employee id", "rate"):
        if need not in cols:
            raise ValueError(f"Missing column: {need.title()}")
    done, problems = 0, []
    for i, r in table.iterrows():
        def cell(n):
            c = cols.get(n)
            v = r[c] if c is not None else None
            return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()
        if not cell("employee id"):
            continue
        try:
            set_pay(db, cell("employee id"), (cell("rate type") or "monthly").lower(), cell("rate"), by, cell("bank") or None)
            done += 1
        except (ValueError, TypeError) as err:
            problems.append({"Row": i + 2, "Employee ID": cell("employee id"), "Problem": str(err)})
    return done, pd.DataFrame(problems, columns=["Row", "Employee ID", "Problem"])


def clear_bank_details(db, by):
    """Remove every stored bank detail, for example when the bank setting is turned off."""
    n = db.run([("UPDATE employees SET bank_enc = NULL WHERE bank_enc IS NOT NULL", ())])[0]
    k.log(db, by, "clear_bank_details", f"{n} records")
    return n


def set_employee_active(db, emp_id, active, by):
    db.run([("UPDATE employees SET active = ? WHERE emp_id = ?", (1 if active else 0, emp_id))])
    k.log(db, by, "activate_employee" if active else "deactivate_employee", emp_id)


def list_employees(db, with_pay=False, active_only=False, branch_code=None):
    """Employee list. with_pay=True adds rate (and bank, when stored): only for payroll roles."""
    sql = """SELECT emp_id, username, full_name, branch_code, position, employment_status, civil_status,
                    date_hired, rate_type, rate_enc, bank_enc, active FROM employees"""
    where, params = [], []
    if active_only:
        where.append("active = 1")
    if branch_code:
        where.append("branch_code = ?"); params.append(branch_code)
    if where:
        sql += " WHERE " + " AND ".join(where)
    df = db.query(sql + " ORDER BY emp_id", params)
    df["active"] = df["active"].astype(int)
    if with_pay:
        df["rate"] = pd.Series([float(_dec(v)) if isinstance(v, str) else None for v in df["rate_enc"]], dtype=object)
        df["bank"] = pd.Series([_dec(v) for v in df["bank_enc"]], dtype=object)
    return df.drop(columns=["rate_enc", "bank_enc"])


def employee_rate(db, username):
    row = db.one("SELECT rate_type, rate_enc FROM employees WHERE username = ? AND active = 1", (username,))
    if not row or not row[1]:
        return None, None
    return row[0], float(_dec(row[1]))


EMP_COLUMNS = ["Employee ID", "Full Name", "Username", "Branch", "Position", "Employment Status",
               "Civil Status", "Date Hired", "Rate Type", "Rate"]


def bulk_employees(db, table, by, allow_pay=False):
    """Load employees from a table with EMP_COLUMNS (Employee ID blank = assign one). Rate only with allow_pay."""
    cols = {str(c).strip().lower(): c for c in table.columns}
    if "full name" not in cols:
        raise ValueError("Missing column: Full Name")
    done, problems = [], []
    for i, r in table.iterrows():
        def cell(name):
            c = cols.get(name.lower())
            v = r[c] if c is not None else None
            return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()
        if not cell("Full Name"):
            continue
        try:
            eid = save_employee(db, by, emp_id=cell("Employee ID") or None, full_name=cell("Full Name"),
                                username=cell("Username") or None, branch_code=cell("Branch") or None,
                                position=cell("Position") or None,
                                employment_status=cell("Employment Status") or "Probationary",
                                civil_status=cell("Civil Status") or "Single",
                                date_hired=cell("Date Hired") or None,
                                rate_type=(cell("Rate Type") or "monthly").lower(),
                                rate=(cell("Rate").replace(",", "") or None) if allow_pay else None)
            done.append({"Row": i + 2, "Employee ID": eid, "Full Name": cell("Full Name")})
        except (ValueError, TypeError) as err:
            problems.append({"Row": i + 2, "Full Name": cell("Full Name"), "Problem": str(err)})
    return (pd.DataFrame(done, columns=["Row", "Employee ID", "Full Name"]),
            pd.DataFrame(problems, columns=["Row", "Full Name", "Problem"]))


# ---------------------------------------------------------------- schedules
def _hhmm(text):
    text = (str(text) if text is not None else "").strip()
    if not text or text.lower() in ("nan", "none"):
        return None
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?", text)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"Time must look like 08:00, not {text}.")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _username_for(db, who):
    """Accept a username or an employee ID; return the username."""
    who = (who or "").strip()
    row = db.one("SELECT username FROM employees WHERE emp_id = ?", (who,))
    if row and row[0]:
        return row[0]
    if db.one("SELECT COUNT(*) FROM users WHERE username = ?", (who.lower(),))[0]:
        return who.lower()
    raise ValueError(f"{who} is not an employee ID linked to an account, or a username.")


def set_schedule(db, username, day, shift_start=None, shift_end=None, break_minutes=60, rest_day=False, by="system"):
    day = pd.Timestamp(day).date()
    s, e = _hhmm(shift_start), _hhmm(shift_end)
    if not rest_day and (not s or not e):
        raise ValueError("A working day needs a start and an end time.")
    if rest_day:
        s = e = None
    db.run([("DELETE FROM schedules WHERE username = ? AND work_date = ?", (username, str(day))),
            ("""INSERT INTO schedules (username, work_date, shift_start, shift_end, break_minutes, rest_day, updated_by, updated_at)
                VALUES (?,?,?,?,?,?,?,?)""", (username, str(day), s, e, int(break_minutes or 0), 1 if rest_day else 0, by, k.now()))])


DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def read_schedule_table(db, table):
    """Turn an uploaded schedule into rows (username, date, start, end, break, rest).
    Two shapes are accepted:
      by date:  Employee, Date, Start, End, Break Minutes, Rest Day
      weekly:   Employee, Day (Mon..Sun), Start, End, Break Minutes, Rest Day, From, To
    Employee is an employee ID or a username. Rest Day is Yes/No. Returns (rows, problems)."""
    cols = {str(c).strip().lower(): c for c in table.columns}
    if "employee" not in cols:
        raise ValueError("Missing column: Employee")
    weekly = "day" in cols
    if weekly and ("from" not in cols or "to" not in cols):
        raise ValueError("A weekly schedule needs From and To columns.")
    if not weekly and "date" not in cols:
        raise ValueError("Add a Date column (one row per day), or Day, From and To (a weekly pattern).")
    rows, problems = [], []
    for i, r in table.iterrows():
        def cell(name):
            c = cols.get(name)
            v = r[c] if c is not None else None
            return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()
        if not cell("employee"):
            continue
        try:
            user = _username_for(db, cell("employee"))
            rest = cell("rest day").lower() in ("yes", "y", "1", "true")
            s, e = (None, None) if rest else (_hhmm(cell("start")), _hhmm(cell("end")))
            if not rest and (not s or not e):
                raise ValueError("needs Start and End, or Rest Day = Yes")
            brk = int(float(cell("break minutes") or 60))
            if weekly:
                dname = cell("day").lower()[:3]
                if dname not in DAY_NAMES:
                    raise ValueError(f"Day must be Mon to Sun, not {cell('day')}")
                d0, d1 = pd.Timestamp(cell("from")).date(), pd.Timestamp(cell("to")).date()
                if d1 < d0 or (d1 - d0).days > 400:
                    raise ValueError("From must be before To, at most 400 days apart")
                d = d0
                while d <= d1:
                    if d.weekday() == DAY_NAMES[dname]:
                        rows.append((user, d, s, e, brk, rest))
                    d += timedelta(days=1)
            else:
                rows.append((user, pd.Timestamp(cell("date")).date(), s, e, brk, rest))
        except (ValueError, TypeError) as err:
            problems.append({"Row": i + 2, "Employee": cell("employee"), "Problem": str(err)})
    return rows, pd.DataFrame(problems, columns=["Row", "Employee", "Problem"])


def import_schedules(db, rows, by):
    """Save schedule rows. A row for the same person and date replaces the old one."""
    stamp = k.now()
    for i in range(0, len(rows), 400):
        part = rows[i:i + 400]
        stmts = []
        for u, d, s, e, brk, rest in part:
            stmts.append(("DELETE FROM schedules WHERE username = ? AND work_date = ?", (u, str(d))))
            stmts.append(("""INSERT INTO schedules (username, work_date, shift_start, shift_end, break_minutes, rest_day, updated_by, updated_at)
                             VALUES (?,?,?,?,?,?,?,?)""", (u, str(d), s, e, int(brk), 1 if rest else 0, by, stamp)))
        db.run(stmts)
    k.log(db, by, "import_schedules", f"{len(rows)} rows")
    return len(rows)


def get_schedules(db, start, end, usernames=None):
    df = db.query("""SELECT username, work_date, shift_start, shift_end, break_minutes, rest_day
                     FROM schedules WHERE work_date >= ? AND work_date <= ? ORDER BY work_date, username""",
                  (str(start), str(end)))
    if usernames is not None:
        df = df[df["username"].isin(list(usernames))]
    df["rest_day"] = df["rest_day"].astype(int)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- holidays
def set_holiday(db, day, name, kind, by):
    if kind not in ("regular", "special"):
        raise ValueError("Holiday kind must be regular or special.")
    if not (name or "").strip():
        raise ValueError("Enter the holiday name.")
    db.run([("DELETE FROM holidays WHERE hdate = ?", (str(pd.Timestamp(day).date()),)),
            ("INSERT INTO holidays (hdate, name, kind) VALUES (?,?,?)", (str(pd.Timestamp(day).date()), name.strip(), kind))])
    k.log(db, by, "set_holiday", f"{day} {name} {kind}")


def remove_holiday(db, day, by):
    db.run([("DELETE FROM holidays WHERE hdate = ?", (str(pd.Timestamp(day).date()),))])
    k.log(db, by, "remove_holiday", str(day))


def get_holidays(db, start=None, end=None):
    if start is None:
        return db.query("SELECT hdate, name, kind FROM holidays ORDER BY hdate")
    return db.query("SELECT hdate, name, kind FROM holidays WHERE hdate >= ? AND hdate <= ? ORDER BY hdate",
                    (str(start), str(end)))


# ---------------------------------------------------------------- approvals (shared by attendance and leave)
def can_approve(db, approver, username):
    """True when approver (a user dict) may approve requests of username."""
    if approver["role"] in ("hr", "manager", "owner"):
        return approver["username"] != username or approver["role"] == "owner"
    if approver["role"] == "supervisor":
        row = db.one("SELECT branch_code FROM users WHERE username = ?", (username,))
        return bool(row) and row[0] == approver["branch_code"] and approver["username"] != username
    return False


def _visible(db, approver, df):
    """Keep only rows (with a username column) the approver may act on."""
    if df.empty:
        return df
    keep = [can_approve(db, approver, u) for u in df["username"]]
    return df[keep].reset_index(drop=True)


# ---------------------------------------------------------------- attendance requests
def request_attendance(db, username, work_date, kind, reason, req_in=None, req_out=None, ot_hours=None):
    """An employee asks for a correction or overtime. Times are local 'HH:MM'."""
    if kind not in REQUEST_KINDS:
        raise ValueError("Unknown request type.")
    if not (reason or "").strip():
        raise ValueError("Enter a reason.")
    d = pd.Timestamp(work_date).date()
    if d > a.local_today():
        raise ValueError("You cannot request a change for a future date.")
    ri, ro = _hhmm(req_in), _hhmm(req_out)
    if kind == "Overtime":
        if not ot_hours or float(ot_hours) <= 0 or float(ot_hours) > 12:
            raise ValueError("Overtime hours must be more than 0 and at most 12.")
    elif not ri and not ro:
        raise ValueError("Enter the correct time in, time out, or both.")
    if ri and ro and ro <= ri:
        raise ValueError("Time out must be after time in. For a night shift, send two requests, one per date.")
    rid = secrets.token_hex(8)
    db.run([("""INSERT INTO att_requests (id, username, work_date, kind, req_in, req_out, ot_hours, reason, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,'Pending',?)""",
             (rid, username, str(d), kind, ri, ro, float(ot_hours) if ot_hours else None, reason.strip(), k.now()))])
    k.log(db, username, "request_attendance", f"{d} {kind}")
    return rid


def list_att_requests(db, username=None, status=None, approver=None):
    sql = """SELECT r.id, r.username, u.full_name, u.branch_code, r.work_date, r.kind, r.req_in, r.req_out,
                    r.ot_hours, r.reason, r.status, r.created_at, r.reviewed_by, r.reviewed_at, r.review_note
             FROM att_requests r JOIN users u ON u.username = r.username"""
    where, params = [], []
    if username:
        where.append("r.username = ?"); params.append(username)
    if status:
        where.append("r.status = ?"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    df = db.query(sql + " ORDER BY r.created_at DESC", params)
    return _visible(db, approver, df) if approver else df


def review_att_request(db, request_id, approve, approver, note=""):
    """Approve or reject. An approved correction updates or adds the attendance record for that date."""
    row = db.one("SELECT username, work_date, kind, req_in, req_out, status FROM att_requests WHERE id = ?", (request_id,))
    if not row:
        raise ValueError("Request not found.")
    username, wd, kind, ri, ro, status = row
    if status != "Pending":
        raise ValueError(f"This request is already {status.lower()}.")
    if not can_approve(db, approver, username):
        raise ValueError("You cannot approve requests for this person.")
    if approve and kind != "Overtime":
        day = pd.Timestamp(wd).date()
        recs = a.records(db, day, day, username=username)
        if len(recs):
            first = recs.sort_values("time_in").iloc[0]
            new_in = datetime.combine(day, datetime.strptime(ri, "%H:%M").time()) if ri else first["in_local"]
            if ro:
                new_out = datetime.combine(day, datetime.strptime(ro, "%H:%M").time())
            else:
                new_out = first["out_local"] if first["out_local"] is not None and not pd.isna(first["out_local"]) else None
            a.correct_record(db, first["id"], new_in, new_out, f"Approved request: {kind}", approver["username"])
        else:
            if not ri or not ro:
                raise ValueError("There is no record for that date. The request needs both time in and time out.")
            a.add_record(db, username, datetime.combine(day, datetime.strptime(ri, "%H:%M").time()),
                         datetime.combine(day, datetime.strptime(ro, "%H:%M").time()),
                         f"Approved request: {kind}", approver["username"])
    db.run([("UPDATE att_requests SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
             ("Approved" if approve else "Rejected", approver["username"], k.now(), (note or "").strip(), request_id))])
    k.log(db, approver["username"], "approve_request" if approve else "reject_request", f"{username} {wd} {kind}")


def approved_overtime(db, start, end):
    df = db.query("""SELECT username, work_date, SUM(ot_hours) AS ot_hours FROM att_requests
                     WHERE kind = 'Overtime' AND status = 'Approved' AND work_date >= ? AND work_date <= ?
                     GROUP BY username, work_date""", (str(start), str(end)))
    df["ot_hours"] = df["ot_hours"].astype(float)
    return df


# ---------------------------------------------------------------- leave
def leave_types(db, active_only=True):
    df = db.query("SELECT code, name, paid, days_per_year, active FROM leave_types ORDER BY code")
    for c in ("paid", "active"):
        df[c] = df[c].astype(int)
    df["days_per_year"] = df["days_per_year"].astype(float)
    return df[df["active"] == 1].reset_index(drop=True) if active_only else df


def save_leave_type(db, code, name, paid, days_per_year, by):
    code = (code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,8}", code):
        raise ValueError("Leave code: 1 to 8 letters or numbers.")
    if not (name or "").strip():
        raise ValueError("Enter the leave name.")
    db.run([("DELETE FROM leave_types WHERE code = ?", (code,)),
            ("INSERT INTO leave_types (code, name, paid, days_per_year, active) VALUES (?,?,?,?,1)",
             (code, name.strip(), 1 if paid else 0, float(days_per_year or 0)))])
    k.log(db, by, "save_leave_type", code)


def set_leave_balance(db, username, year, code, entitled, by):
    db.run([("DELETE FROM leave_balances WHERE username = ? AND year = ? AND code = ?", (username, int(year), code)),
            ("INSERT INTO leave_balances (username, year, code, entitled) VALUES (?,?,?,?)",
             (username, int(year), code, float(entitled)))])
    k.log(db, by, "set_leave_balance", f"{username} {year} {code} {entitled}")


def leave_balances(db, username, year):
    """Entitled, used (approved) and remaining days per leave type for a person and year."""
    t = leave_types(db)
    own = db.query("SELECT code, entitled FROM leave_balances WHERE username = ? AND year = ?", (username, int(year)))
    used = db.query("""SELECT code, SUM(days) AS used FROM leave_requests
                       WHERE username = ? AND status = 'Approved' AND start_date >= ? AND start_date <= ?
                       GROUP BY code""", (username, f"{year}-01-01", f"{year}-12-31"))
    out = t.merge(own, on="code", how="left").merge(used, on="code", how="left")
    out["entitled"] = out["entitled"].astype(float).fillna(out["days_per_year"])
    out["used"] = out["used"].astype(float).fillna(0.0)
    out["remaining"] = out["entitled"] - out["used"]
    return out[["code", "name", "paid", "entitled", "used", "remaining"]]


def working_days(db, username, start, end):
    """Days in the range that are not rest days or holidays. Uses the schedule where there is one,
    else Monday to Saturday."""
    s = get_schedules(db, start, end, [username]).set_index("work_date")
    hol = set(get_holidays(db, start, end)["hdate"])
    n, d = 0, pd.Timestamp(start).date()
    while d <= pd.Timestamp(end).date():
        key = str(d)
        if key not in hol:
            if key in s.index:
                n += 0 if int(s.loc[key, "rest_day"]) else 1
            else:
                n += 1 if d.weekday() < 6 else 0
        d += timedelta(days=1)
    return n


def request_leave(db, username, code, start, end, reason="", half_day=False):
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    if end < start:
        raise ValueError("The end date must be on or after the start date.")
    t = leave_types(db).set_index("code")
    if code not in t.index:
        raise ValueError("Unknown leave type.")
    clash = db.one("""SELECT COUNT(*) FROM leave_requests WHERE username = ? AND status IN ('Pending','Approved')
                      AND start_date <= ? AND end_date >= ?""", (username, str(end), str(start)))[0]
    if clash:
        raise ValueError("You already have leave requested for some of these dates.")
    days = 0.5 if half_day and start == end else float(working_days(db, username, start, end))
    if days <= 0:
        raise ValueError("Those dates are all rest days or holidays.")
    if int(t.loc[code, "paid"]):
        bal = leave_balances(db, username, start.year).set_index("code")
        pending = float(db.one("""SELECT COALESCE(SUM(days), 0) FROM leave_requests WHERE username = ? AND code = ?
                                  AND status = 'Pending' AND start_date >= ? AND start_date <= ?""",
                               (username, code, f"{start.year}-01-01", f"{start.year}-12-31"))[0])
        left = float(bal.loc[code, "remaining"]) - pending if code in bal.index else 0
        if code in bal.index and float(bal.loc[code, "entitled"]) > 0 and days > left:
            raise ValueError(f"Not enough {t.loc[code, 'name']} left: {left:g} days, counting pending requests.")
    rid = secrets.token_hex(8)
    db.run([("""INSERT INTO leave_requests (id, username, code, start_date, end_date, days, reason, status, created_at)
                VALUES (?,?,?,?,?,?,?,'Pending',?)""", (rid, username, code, str(start), str(end), days, (reason or "").strip(), k.now()))])
    k.log(db, username, "request_leave", f"{code} {start} to {end} ({days:g} days)")
    return rid


def list_leave_requests(db, username=None, status=None, approver=None):
    sql = """SELECT r.id, r.username, u.full_name, u.branch_code, r.code, t.name AS leave_name, r.start_date,
                    r.end_date, r.days, r.reason, r.status, r.created_at, r.reviewed_by, r.reviewed_at, r.review_note
             FROM leave_requests r JOIN users u ON u.username = r.username
             LEFT JOIN leave_types t ON t.code = r.code"""
    where, params = [], []
    if username:
        where.append("r.username = ?"); params.append(username)
    if status:
        where.append("r.status = ?"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    df = db.query(sql + " ORDER BY r.created_at DESC", params)
    df["days"] = df["days"].astype(float)
    return _visible(db, approver, df) if approver else df


def review_leave(db, request_id, approve, approver, note=""):
    row = db.one("SELECT username, status, code, start_date FROM leave_requests WHERE id = ?", (request_id,))
    if not row:
        raise ValueError("Request not found.")
    if row[1] != "Pending":
        raise ValueError(f"This request is already {row[1].lower()}.")
    if not can_approve(db, approver, row[0]):
        raise ValueError("You cannot approve requests for this person.")
    db.run([("UPDATE leave_requests SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ? WHERE id = ?",
             ("Approved" if approve else "Rejected", approver["username"], k.now(), (note or "").strip(), request_id))])
    k.log(db, approver["username"], "approve_leave" if approve else "reject_leave", f"{row[0]} {row[2]} {row[3]}")


def cancel_request(db, table, request_id, username):
    """The person who asked may cancel a request that is still pending."""
    if table not in ("att_requests", "leave_requests"):
        raise ValueError("Unknown request table.")
    n = db.run([(f"UPDATE {table} SET status = 'Cancelled' WHERE id = ? AND username = ? AND status = 'Pending'",
                 (request_id, username))])[0]
    if n != 1:
        raise ValueError("Only your own pending requests can be cancelled.")


def approved_leave_days(db, start, end):
    """One row per person per date on approved leave: username, work_date, code, paid, fraction."""
    reqs = db.query("""SELECT r.username, r.code, r.start_date, r.end_date, r.days, t.paid FROM leave_requests r
                       LEFT JOIN leave_types t ON t.code = r.code
                       WHERE r.status = 'Approved' AND r.start_date <= ? AND r.end_date >= ?""", (str(end), str(start)))
    hol = set(get_holidays(db, start, end)["hdate"])
    rows = []
    for _, r in reqs.iterrows():
        d0, d1 = pd.Timestamp(r["start_date"]).date(), pd.Timestamp(r["end_date"]).date()
        frac = 0.5 if float(r["days"]) == 0.5 else 1.0
        sched = get_schedules(db, d0, d1, [r["username"]]).set_index("work_date")
        d = d0
        while d <= d1:
            key = str(d)
            rest = int(sched.loc[key, "rest_day"]) if key in sched.index else (1 if d.weekday() == 6 else 0)
            if pd.Timestamp(start).date() <= d <= pd.Timestamp(end).date() and key not in hol and not rest:
                rows.append((r["username"], key, r["code"], int(r["paid"] if r["paid"] is not None else 1), frac))
            d += timedelta(days=1)
    return pd.DataFrame(rows, columns=["username", "work_date", "code", "paid", "fraction"])


# ---------------------------------------------------------------- daily attendance status
def _night_hours(t0, t1):
    """Hours between 22:00 and 06:00 inside [t0, t1]."""
    if t0 is None or t1 is None or t1 <= t0:
        return 0.0
    total, d = 0.0, (t0 - timedelta(days=1)).date()
    while datetime.combine(d, datetime.min.time()) <= t1:
        n0 = datetime.combine(d, datetime.min.time()) + timedelta(hours=22)
        n1 = n0 + timedelta(hours=8)
        lo, hi = max(t0, n0), min(t1, n1)
        if hi > lo:
            total += (hi - lo).total_seconds() / 3600
        d += timedelta(days=1)
    return total


def daily_status(db, start, end, usernames=None, today=None, grace_minutes=None):
    """One row per person per date in the range, for people with a schedule, a record or leave.
    Columns: username, work_date, scheduled, rest_day, holiday, holiday_kind, leave_code, leave_paid,
    leave_fraction, first_in, last_out, worked_hours, late_min, undertime_min, ot_hours, night_hours, status."""
    today = pd.Timestamp(today or a.local_today()).date()
    grace = int(grace_minutes if grace_minutes is not None else get_setting(db, "grace_minutes", "0"))
    sched = get_schedules(db, start, end, usernames)
    recs = a.records(db, start, end)
    if usernames is not None:
        recs = recs[recs["username"].isin(list(usernames))]
    hol = get_holidays(db, start, end).set_index("hdate")
    lv = approved_leave_days(db, start, end)
    if usernames is not None:
        lv = lv[lv["username"].isin(list(usernames))]
    ot = approved_overtime(db, start, end)
    keys = set(zip(sched["username"], sched["work_date"])) | set(zip(recs["username"], recs["work_date"])) | \
        set(zip(lv["username"], lv["work_date"]))
    s_idx = sched.set_index(["username", "work_date"])
    lv_idx = lv.drop_duplicates(["username", "work_date"]).set_index(["username", "work_date"])
    ot_idx = ot.set_index(["username", "work_date"])
    out = []
    for u, wd in sorted(keys, key=lambda x: (x[1], x[0])):
        d = pd.Timestamp(wd).date()
        row = {"username": u, "work_date": wd, "scheduled": False, "rest_day": False, "holiday": wd in hol.index,
               "holiday_kind": hol.loc[wd, "kind"] if wd in hol.index else None, "leave_code": None,
               "leave_paid": None, "leave_fraction": 0.0, "first_in": None, "last_out": None, "worked_hours": 0.0,
               "late_min": 0.0, "undertime_min": 0.0, "ot_hours": 0.0, "night_hours": 0.0, "shift_start": None,
               "shift_end": None}
        if (u, wd) in s_idx.index:
            sr = s_idx.loc[(u, wd)]
            row["rest_day"] = bool(int(sr["rest_day"]))
            row["scheduled"] = not row["rest_day"]
            row["shift_start"], row["shift_end"], brk = sr["shift_start"], sr["shift_end"], int(sr["break_minutes"])
        else:
            brk = 60
        if (u, wd) in lv_idx.index:
            lr = lv_idx.loc[(u, wd)]
            row["leave_code"], row["leave_paid"], row["leave_fraction"] = lr["code"], int(lr["paid"]), float(lr["fraction"])
        mine = recs[(recs["username"] == u) & (recs["work_date"] == wd)]
        if len(mine):
            ins = [x for x in mine["in_local"] if x is not None]
            outs = [x for x in mine["out_local"] if x is not None and not pd.isna(x)]
            row["first_in"] = min(ins) if ins else None
            row["last_out"] = max(outs) if outs else None
            hours = float(mine["hours"].sum(min_count=1)) if mine["hours"].notna().any() else 0.0
            if hours > 5 and brk:
                hours -= brk / 60
            row["worked_hours"] = max(hours, 0.0)
            row["night_hours"] = sum(_night_hours(i, o) for i, o in zip(mine["in_local"], mine["out_local"])
                                     if o is not None and not pd.isna(o))
        if row["scheduled"] and row["shift_start"]:
            ss = datetime.combine(d, datetime.strptime(row["shift_start"], "%H:%M").time())
            se = datetime.combine(d, datetime.strptime(row["shift_end"], "%H:%M").time())
            if se <= ss:
                se += timedelta(days=1)
            if row["first_in"] is not None:
                late = (row["first_in"] - ss).total_seconds() / 60
                row["late_min"] = late if late > grace else 0.0
            if row["last_out"] is not None:
                row["undertime_min"] = max((se - row["last_out"]).total_seconds() / 60, 0.0)
        if (u, wd) in ot_idx.index:
            row["ot_hours"] = float(ot_idx.loc[(u, wd), "ot_hours"])
        worked = row["first_in"] is not None
        if row["leave_code"] and row["leave_fraction"] >= 1:
            st = "On leave"
        elif row["holiday"] and not worked:
            st = "Holiday"
        elif row["rest_day"]:
            st = "Rest day worked" if worked else "Rest day"
        elif not row["scheduled"]:
            st = "Worked, no schedule" if worked else "No schedule"
        elif not worked:
            st = "Absent" if d < today else ("Not in yet" if d == today else "Scheduled")
        elif row["last_out"] is None:
            st = "No time out" if d < today else "In"
        elif row["late_min"] > 0:
            st = "Late"
        elif row["undertime_min"] > 0:
            st = "Undertime"
        else:
            st = "Present"
        if row["holiday"] and worked:
            st = "Holiday worked"
        row["status"] = st
        out.append(row)
    cols = ["username", "work_date", "scheduled", "rest_day", "holiday", "holiday_kind", "leave_code", "leave_paid",
            "leave_fraction", "first_in", "last_out", "worked_hours", "late_min", "undertime_min", "ot_hours",
            "night_hours", "shift_start", "shift_end", "status"]
    return pd.DataFrame(out, columns=cols)


def attendance_summary(db, start, end, usernames=None, today=None):
    """Per person: days present, late count and minutes, undertime minutes, absences, leave days,
    approved overtime hours, night hours."""
    ds = daily_status(db, start, end, usernames, today)
    users = db.query("SELECT username, full_name, branch_code FROM users WHERE active = 1")
    if usernames is not None:
        users = users[users["username"].isin(list(usernames))]
    if ds.empty:
        g = pd.DataFrame(columns=["username"])
    else:
        ds["present"] = ds["first_in"].notna()
        g = ds.groupby("username").agg(
            days_present=("present", "sum"), late_count=("late_min", lambda s: int((s > 0).sum())),
            late_min=("late_min", "sum"), undertime_min=("undertime_min", "sum"),
            absences=("status", lambda s: int((s == "Absent").sum())),
            no_time_out=("status", lambda s: int((s == "No time out").sum())),
            leave_days=("leave_fraction", "sum"), ot_hours=("ot_hours", "sum"),
            night_hours=("night_hours", "sum"), worked_hours=("worked_hours", "sum")).reset_index()
    out = users.merge(g, on="username", how="left")
    for c in ("days_present", "late_count", "absences", "no_time_out"):
        out[c] = out[c].fillna(0).astype(int)
    for c in ("late_min", "undertime_min", "leave_days", "ot_hours", "night_hours", "worked_hours"):
        out[c] = out[c].astype(float).fillna(0.0)
    return out.sort_values(["branch_code", "full_name"], na_position="last").reset_index(drop=True)
