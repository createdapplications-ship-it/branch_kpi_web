"""Database, accounts and calculation layer for the Branch KPI web app.

No Streamlit code in this file, so it can be tested on its own.

Database: PostgreSQL when DATABASE_URL is set, otherwise a local SQLite file (for trying it on a PC).
Rules:
  Adjusted Value = Metric Value x multiplier
  Branches are ranked by total Adjusted Value for the period. Rank 1 is the highest.
  A missing entry means "not submitted". A 0 is a real reported value.
"""
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
SQLITE_PATH = Path(os.environ.get("KPI_DB", BASE / "kpi.db"))
ROLES = ("employee", "branch", "manager", "owner")
ROLE_CHECK = "role IN ('employee','branch','manager','owner')"
MIN_PASSWORD = 8
HASH_ROUNDS = 200_000
SESSION_HOURS = 12
CLUSTER_SIZE = 5
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


# ---------------------------------------------------------------- connection
class DB:
    """Small wrapper so the same code runs on PostgreSQL and SQLite."""

    def __init__(self, url=None):
        self.url = url or ""
        self.is_pg = self.url.startswith(("postgres://", "postgresql://"))
        self.raw = None
        self.connect()

    def connect(self):
        if self.is_pg:
            import psycopg2  # only needed for PostgreSQL
            self.raw = psycopg2.connect(self.url)
        else:
            self.raw = sqlite3.connect(SQLITE_PATH, check_same_thread=False)

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.is_pg else sql

    def _cursor(self):
        """Return a cursor. Reconnect once if a hosted database closed the idle connection."""
        if self.is_pg:
            try:
                cur = self.raw.cursor()
                cur.execute("SELECT 1")
                cur.fetchall()
                return cur
            except Exception:
                try:
                    self.raw.close()
                except Exception:
                    pass
                self.connect()
        return self.raw.cursor()

    def query(self, sql, params=()):
        """Run a SELECT and return a DataFrame (with column names even when empty)."""
        cur = self._cursor()
        try:
            cur.execute(self._sql(sql), tuple(params))
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            self.raw.commit()
        except Exception:
            self.raw.rollback()
            raise
        return pd.DataFrame(rows, columns=cols)

    def one(self, sql, params=()):
        df = self.query(sql, params)
        return None if df.empty else df.iloc[0].tolist()

    def run(self, statements):
        """Run a list of (sql, params) in one transaction. Returns the row count of each."""
        cur = self._cursor()
        counts = []
        try:
            for sql, params in statements:
                cur.execute(self._sql(sql), tuple(params))
                counts.append(cur.rowcount)
            self.raw.commit()
        except Exception:
            self.raw.rollback()
            raise
        return counts

    def insert_many(self, table, columns, rows, chunk=1000):
        """Insert many rows with a few large statements (fast on a remote database)."""
        if not self.is_pg:
            chunk = max(1, 900 // len(columns))   # stay under SQLite's variable limit
        one = "(" + ",".join("?" * len(columns)) + ")"
        for i in range(0, len(rows), chunk):
            part = rows[i:i + chunk]
            sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES " + ",".join([one] * len(part))
            self.run([(sql, [v for r in part for v in r])])


def connect(url=None):
    return DB(url if url is not None else os.environ.get("DATABASE_URL", ""))


def now():
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- schema
def schema(is_pg):
    d, num = ("DATE", "DOUBLE PRECISION") if is_pg else ("TEXT", "REAL")
    return [
        "CREATE TABLE IF NOT EXISTS branches (branch_code TEXT PRIMARY KEY, branch TEXT NOT NULL)",
        f"CREATE TABLE IF NOT EXISTS metrics (metric TEXT PRIMARY KEY, multiplier {num} NOT NULL)",
        f"""CREATE TABLE IF NOT EXISTS entries (
            branch_code TEXT NOT NULL REFERENCES branches(branch_code),
            date {d} NOT NULL,
            metric TEXT NOT NULL REFERENCES metrics(metric),
            value {num} NOT NULL CHECK (value >= 0),
            updated_at TEXT, updated_by TEXT,
            PRIMARY KEY (branch_code, date, metric))""",
        f"""CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK ({ROLE_CHECK}),
            branch_code TEXT REFERENCES branches(branch_code),
            must_change INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT)""",
        "CREATE TABLE IF NOT EXISTS audit_log (at TEXT, username TEXT, action TEXT, detail TEXT)",
        """CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, created_at TEXT, expires_at TEXT NOT NULL)""",
        "CREATE TABLE IF NOT EXISTS login_attempts (username TEXT NOT NULL, at TEXT NOT NULL, ok INTEGER NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_entries_date ON entries (date)",
        """CREATE TABLE IF NOT EXISTS att_records (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            work_date TEXT NOT NULL,
            time_in TEXT NOT NULL,
            time_out TEXT,
            note TEXT,
            edited_by TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_att_records_date ON att_records (work_date)",
        "CREATE INDEX IF NOT EXISTS idx_att_records_user ON att_records (username)",
    ]


def ensure_column(db, table, column, definition):
    """Add a column to an existing table if it is missing. Keeps older databases working after an update."""
    if db.is_pg:
        db.run([(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}", ())])
    else:
        cols = db.query(f"SELECT name FROM pragma_table_info('{table}')")["name"].tolist()
        if column not in cols:
            db.run([(f"ALTER TABLE {table} ADD COLUMN {column} {definition}", ())])


def migrate_roles(db):
    """Older databases allow three roles only. Allow the employee role (Attendance only) as well."""
    if db.is_pg:
        db.run([("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check", ()),
                (f"ALTER TABLE users ADD CONSTRAINT users_role_check CHECK ({ROLE_CHECK})", ())])
        return
    made = db.one("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'")[0]
    if "'employee'" in made:
        return
    create = [x for x in schema(False) if "TABLE IF NOT EXISTS users" in x][0]
    cols = "username, full_name, password_hash, salt, role, branch_code, must_change, active, created_at"
    db.run([("ALTER TABLE users RENAME TO users_old", ()), (create, ()),
            (f"INSERT INTO users ({cols}) SELECT {cols} FROM users_old", ()), ("DROP TABLE users_old", ())])


def init_db(db, admin_username=None, admin_password=None, load_sample=True):
    """Create tables. Load reference data, and the sample entries if asked, on first run.
    Create the first owner account from admin_username and admin_password if no owner exists."""
    db.run([(s, ()) for s in schema(db.is_pg)])
    ensure_column(db, "metrics", "active", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(db, "branches", "cluster", "TEXT")
    migrate_roles(db)
    if db.one("SELECT COUNT(*) FROM branches")[0] == 0:
        b = pd.read_csv(DATA_DIR / "branches.csv")
        m = pd.read_csv(DATA_DIR / "metrics.csv")
        db.insert_many("branches", ["branch_code", "branch"], b[["branch_code", "branch"]].values.tolist())
        db.insert_many("metrics", ["metric", "multiplier"], [[r[0], float(r[1])] for r in m.values.tolist()])
        if load_sample:
            e = pd.read_csv(DATA_DIR / "sample_entries.csv")
            stamp = now()
            rows = [[r[0], r[1], r[2], float(r[3]), stamp, "sample"] for r in e.values.tolist()]
            db.insert_many("entries", ["branch_code", "date", "metric", "value", "updated_at", "updated_by"], rows)
    fill_clusters(db)
    has_owner = db.one("SELECT COUNT(*) FROM users WHERE role = 'owner' AND active = 1")[0] > 0
    if not has_owner and admin_username and admin_password:
        create_user(db, admin_username, "Dashboard owner", "owner", None, admin_password,
                    by="setup", must_change=False)
    return db.one("SELECT COUNT(*) FROM users WHERE role = 'owner' AND active = 1")[0] > 0


# ---------------------------------------------------------------- accounts
def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), HASH_ROUNDS).hex()


def check_password_rules(password):
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters.")
    if password.isdigit() or password.isalpha():
        raise ValueError("Password must have both letters and numbers.")


def new_temp_password():
    """A random temporary password, shown once to the admin."""
    words = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
    return f"{words}{secrets.randbelow(90) + 10}"


def create_user(db, username, full_name, role, branch_code, password, by, must_change=True):
    username = (username or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", username):
        raise ValueError("Username: 3 to 40 characters, letters, numbers, dot, dash or underscore.")
    if role not in ROLES:
        raise ValueError("Unknown role.")
    if role == "branch" and not branch_code:
        raise ValueError("A branch user needs a branch.")
    branch_code = (branch_code or "").strip() or None
    if branch_code and not db.one("SELECT COUNT(*) FROM branches WHERE branch_code = ?", (branch_code,))[0]:
        raise ValueError(f"{branch_code} is not in the branch list.")
    check_password_rules(password)
    if db.one("SELECT COUNT(*) FROM users WHERE username = ?", (username,))[0]:
        raise ValueError("That username already exists.")
    salt = secrets.token_hex(16)
    db.run([("""INSERT INTO users (username, full_name, password_hash, salt, role, branch_code,
                                  must_change, active, created_at) VALUES (?,?,?,?,?,?,?,1,?)""",
             (username, (full_name or username).strip(), _hash(password, salt), salt, role, branch_code,
              1 if must_change else 0, now()))])
    log(db, by, "create_user", f"{username} ({role}{' ' + branch_code if branch_code else ''})")
    return username


def is_locked(db, username):
    """True when the account has too many wrong passwords in the last LOCK_MINUTES."""
    since = (datetime.now() - timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="microseconds")
    last_ok = db.one("SELECT MAX(at) FROM login_attempts WHERE username = ? AND ok = 1", (username,))[0]
    start = max(since, last_ok) if last_ok else since
    failed = db.one("SELECT COUNT(*) FROM login_attempts WHERE username = ? AND ok = 0 AND at > ?",
                    (username, start))[0]
    return int(failed) >= MAX_FAILED_LOGINS


def check_login(db, username, password):
    """Return the user for a correct sign-in, or None. Raises ValueError while the account is locked."""
    username = (username or "").strip().lower()
    if username and is_locked(db, username):
        log(db, username, "login_locked")
        raise ValueError(f"Too many wrong passwords. Try again in {LOCK_MINUTES} minutes, "
                         "or ask the owner to reset your password.")
    row = db.one("""SELECT username, full_name, role, branch_code, password_hash, salt, must_change, active
                    FROM users WHERE username = ?""", (username,))
    good = bool(row and int(row[7]) == 1 and hmac.compare_digest(row[4], _hash(password or "", row[5])))
    if username:
        db.run([("INSERT INTO login_attempts (username, at, ok) VALUES (?,?,?)", (username, datetime.now().isoformat(timespec="microseconds"), 1 if good else 0))])
    if good:
        log(db, username, "login")
        return {"username": row[0], "full_name": row[1], "role": row[2], "branch_code": row[3],
                "must_change": bool(int(row[6]))}
    log(db, username or "(blank)", "login_failed")
    return None


def change_password(db, username, old_password, new_password):
    row = db.one("SELECT password_hash, salt FROM users WHERE username = ? AND active = 1", (username,))
    if not row or not hmac.compare_digest(row[0], _hash(old_password or "", row[1])):
        raise ValueError("Current password is wrong.")
    if new_password == old_password:
        raise ValueError("The new password must be different.")
    check_password_rules(new_password)
    salt = secrets.token_hex(16)
    db.run([("UPDATE users SET password_hash = ?, salt = ?, must_change = 0 WHERE username = ?",
             (_hash(new_password, salt), salt, username))])
    log(db, username, "change_password")


def reset_password(db, username, by):
    """Owner action. Sets a temporary password and returns it. The user must change it at next sign-in."""
    temp = new_temp_password()
    salt = secrets.token_hex(16)
    n = db.run([("UPDATE users SET password_hash = ?, salt = ?, must_change = 1 WHERE username = ?",
                 (_hash(temp, salt), salt, username))])[0]
    if n != 1:
        raise ValueError("User not found.")
    end_user_sessions(db, username)
    db.run([("DELETE FROM login_attempts WHERE username = ?", (username,))])   # also unlocks the account
    log(db, by, "reset_password", username)
    return temp


def set_active(db, username, active, by):
    if not active:
        row = db.one("SELECT role FROM users WHERE username = ?", (username,))
        owners = db.one("SELECT COUNT(*) FROM users WHERE role = 'owner' AND active = 1")[0]
        if row and row[0] == "owner" and owners <= 1:
            raise ValueError("At least one active owner is required.")
    db.run([("UPDATE users SET active = ? WHERE username = ?", (1 if active else 0, username))])
    if not active:
        end_user_sessions(db, username)
    log(db, by, "activate_user" if active else "deactivate_user", username)


# ---------------------------------------------------------------- sessions
# A session keeps a user signed in after a page refresh. The browser holds a random token.
# Only a hash of the token is stored, and it stops working after SESSION_HOURS or at sign-out.
def _token_hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()


def create_session(db, username, hours=SESSION_HOURS):
    token = secrets.token_urlsafe(32)
    stamp = datetime.now()
    db.run([("DELETE FROM sessions WHERE expires_at < ?", (stamp.isoformat(timespec="seconds"),)),
            ("DELETE FROM login_attempts WHERE at < ?", ((stamp - timedelta(days=1)).isoformat(timespec="seconds"),)),
            ("INSERT INTO sessions (token_hash, username, created_at, expires_at) VALUES (?,?,?,?)",
             (_token_hash(token), username, stamp.isoformat(timespec="seconds"),
              (stamp + timedelta(hours=hours)).isoformat(timespec="seconds")))])
    return token


def get_session_user(db, token):
    """Return the signed-in user for a token, or None if it is unknown, expired or the user is inactive."""
    if not token or len(token) < 20:
        return None
    row = db.one("""SELECT u.username, u.full_name, u.role, u.branch_code, u.must_change
                    FROM sessions s JOIN users u ON u.username = s.username
                    WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1""",
                 (_token_hash(token), now()))
    if not row:
        return None
    return {"username": row[0], "full_name": row[1], "role": row[2], "branch_code": row[3],
            "must_change": bool(int(row[4]))}


def end_session(db, token):
    if token:
        db.run([("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))])


def end_user_sessions(db, username):
    db.run([("DELETE FROM sessions WHERE username = ?", (username,))])


def bulk_create_users(db, table, by):
    """Create many users from a table with columns Username, Full Name, Role, Branch.
    Role: employee (Attendance only), branch, manager or owner. Branch may be blank except for the branch role.
    Returns (created, problems). created holds each new user's temporary password, shown once."""
    cols = {str(c).strip().lower(): c for c in table.columns}
    missing = [c for c in ("username", "full name", "role", "branch") if c not in cols]
    if missing:
        raise ValueError("Missing column(s): " + ", ".join(c.title() for c in missing))
    created, problems = [], []
    for i, r in table.iterrows():
        def cell(name):
            v = r[cols[name]]
            return "" if pd.isna(v) else str(v).strip()
        if not cell("username"):
            continue
        temp = new_temp_password()
        try:
            name = create_user(db, cell("username"), cell("full name"), cell("role").lower() or "employee",
                               cell("branch"), temp, by)
            created.append({"Username": name, "Full Name": cell("full name"), "Temporary Password": temp})
        except ValueError as err:
            problems.append({"Row": i + 2, "Username": cell("username"), "Problem": str(err)})
    return (pd.DataFrame(created, columns=["Username", "Full Name", "Temporary Password"]),
            pd.DataFrame(problems, columns=["Row", "Username", "Problem"]))


def list_users(db):
    return db.query("""SELECT username, full_name, role, branch_code, must_change, active, created_at
                       FROM users ORDER BY role, username""")


def log(db, username, action, detail=""):
    db.run([("INSERT INTO audit_log (at, username, action, detail) VALUES (?,?,?,?)",
             (now(), username, action, detail))])


def recent_log(db, limit=50):
    return db.query(f"SELECT at, username, action, detail FROM audit_log ORDER BY at DESC LIMIT {int(limit)}")


# ---------------------------------------------------------------- reads
def get_branches(db):
    return db.query("SELECT branch_code, branch, cluster FROM branches ORDER BY branch_code")


def default_cluster(branch_code, size=CLUSTER_SIZE):
    """Branch01 to Branch05 are Cluster01, Branch06 to Branch10 are Cluster02, and so on."""
    n = int(re.search(r"(\d+)$", branch_code).group(1))
    return f"Cluster{(n - 1) // size + 1:02d}"


def fill_clusters(db):
    """Give a cluster to any branch that has none. Clusters already set are left alone."""
    missing = db.query("SELECT branch_code FROM branches WHERE cluster IS NULL OR cluster = ''")
    if len(missing):
        db.run([("UPDATE branches SET cluster = ? WHERE branch_code = ?", (default_cluster(c), c))
                for c in missing["branch_code"]])


def set_cluster(db, branch_code, cluster, username):
    cluster = (cluster or "").strip()
    if not re.fullmatch(r"Cluster\d{2}", cluster):
        raise ValueError("Cluster must look like Cluster01 (the word Cluster and 2 digits).")
    old = db.one("SELECT cluster FROM branches WHERE branch_code = ?", (branch_code,))
    if not old:
        raise ValueError(f"{branch_code} does not exist.")
    db.run([("UPDATE branches SET cluster = ? WHERE branch_code = ?", (cluster, branch_code))])
    log(db, username, "set_cluster", f"{branch_code}: {old[0]} -> {cluster}")


def get_metrics(db, active_only=False):
    """Metric, multiplier and active flag. Inactive metrics keep their history but are not asked for."""
    df = db.query("SELECT metric, multiplier, active FROM metrics ORDER BY metric")
    df["active"] = df["active"].astype(int)
    df["multiplier"] = df["multiplier"].astype(float)
    return df[df["active"] == 1].reset_index(drop=True) if active_only else df


def add_metric(db, metric, multiplier, username):
    name = (metric or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.\-/&%]{0,39}", name):
        raise ValueError("Metric name: 1 to 40 characters, starting with a letter or number.")
    try:
        mult = float(multiplier)
    except (TypeError, ValueError):
        raise ValueError("Enter the multiplier as a number.")
    if mult < 0:
        raise ValueError("The multiplier cannot be negative.")
    if name.lower() in set(get_metrics(db)["metric"].str.lower()):
        raise ValueError(f"The metric {name} already exists.")
    db.run([("INSERT INTO metrics (metric, multiplier, active) VALUES (?,?,1)", (name, mult))])
    log(db, username, "add_metric", f"{name} x {mult}")
    return name


def set_metric_active(db, metric, active, username):
    """Deactivate a metric so it is no longer asked for. Its past entries stay in the totals."""
    if not active:
        left = int(db.one("SELECT COUNT(*) FROM metrics WHERE active = 1 AND metric <> ?", (metric,))[0])
        if left < 1:
            raise ValueError("At least one active metric is required.")
    n = db.run([("UPDATE metrics SET active = ? WHERE metric = ?", (1 if active else 0, metric))])[0]
    if n != 1:
        raise ValueError("Metric not found.")
    log(db, username, "activate_metric" if active else "deactivate_metric", metric)


def remove_sample_data(db, username):
    """Delete the sample entries loaded at first start. Entries typed or imported by users are kept."""
    n = db.run([("DELETE FROM entries WHERE updated_by = ?", ("sample",))])[0]
    log(db, username, "remove_sample_data", f"{n} rows")
    return n


def load_fact(db):
    """All entries with branch name, multiplier and Adjusted Value."""
    df = db.query(
        """SELECT e.branch_code, b.branch, b.cluster, e.date, e.metric, e.value, m.multiplier,
                  e.value * m.multiplier AS adjusted
           FROM entries e
           JOIN branches b ON b.branch_code = e.branch_code
           JOIN metrics m ON m.metric = e.metric""")
    df["date"] = pd.to_datetime(df["date"])
    for c in ("value", "multiplier", "adjusted"):
        df[c] = df[c].astype(float)
    return df


def get_day_entries(db, branch_code, day):
    """The active metrics for one branch and day. Value is blank when not entered."""
    m = get_metrics(db, active_only=True)
    e = db.query("SELECT metric, value FROM entries WHERE branch_code = ? AND date = ?", (branch_code, str(day)))
    out = m.merge(e, on="metric", how="left")
    out["value"] = out["value"].astype(float)
    return out[["metric", "multiplier", "value"]]


# ---------------------------------------------------------------- writes
def save_day_entries(db, branch_code, day, values, username):
    """values: dict metric -> number or None. None removes the entry (not submitted).
    All changes for the day are saved together, or none are."""
    valid = set(get_metrics(db)["metric"])
    stamp = now()
    statements, kinds = [], []
    for metric, v in values.items():
        if metric not in valid:
            raise ValueError(f"Unknown metric: {metric}")
        if v is None or pd.isna(v):
            statements.append(("DELETE FROM entries WHERE branch_code = ? AND date = ? AND metric = ?",
                               (branch_code, str(day), metric)))
            kinds.append("delete")
            continue
        v = float(v)
        if v < 0 or v != int(v):
            raise ValueError(f"{metric}: enter a whole number of 0 or higher")
        statements.append((
            """INSERT INTO entries (branch_code, date, metric, value, updated_at, updated_by)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT (branch_code, date, metric)
               DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at,
                             updated_by = excluded.updated_by""",
            (branch_code, str(day), metric, v, stamp, username)))
        kinds.append("save")
    counts = db.run(statements)
    saved = kinds.count("save")
    removed = sum(c for c, kind in zip(counts, kinds) if kind == "delete" and c and c > 0)
    log(db, username, "save_entries", f"{branch_code} {day}: {saved} saved, {removed} removed")
    return saved, removed


def add_branch(db, branch_code, branch, username, cluster=None):
    """Add a branch to the branch list (the same two fields as Dim_Branch: Branch Code and Branch Name)."""
    code = (branch_code or "").strip()
    name = (branch or "").strip()
    if not re.fullmatch(r"Branch\d{2,3}", code):
        raise ValueError("Branch code must look like Branch21 (the word Branch and 2 or 3 digits).")
    if not name:
        raise ValueError("Enter the branch name.")
    existing = get_branches(db)
    if code.lower() in set(existing["branch_code"].str.lower()):
        raise ValueError(f"{code} already exists.")
    if name.lower() in set(existing["branch"].str.lower()):
        raise ValueError(f"A branch named {name} already exists.")
    cluster = (cluster or "").strip() or default_cluster(code)
    if not re.fullmatch(r"Cluster\d{2}", cluster):
        raise ValueError("Cluster must look like Cluster01 (the word Cluster and 2 digits).")
    db.run([("INSERT INTO branches (branch_code, branch, cluster) VALUES (?,?,?)", (code, name, cluster))])
    log(db, username, "add_branch", f"{code} {name} {cluster}")
    return code


def read_branch_file(file, filename):
    """Read an uploaded branch file (.xlsx with a sheet named data, or .csv) into a DataFrame."""
    if str(filename).lower().endswith(".csv"):
        return pd.read_csv(file)
    try:
        return pd.read_excel(file, sheet_name="data")
    except ValueError:
        raise ValueError('The Excel file needs a sheet named "data".')


def check_branch_file(db, raw):
    """Check an uploaded branch file. Returns (clean rows, list of problems).
    Needs the columns Date, Metric and Metric Value. Blank values are skipped (not submitted)."""
    cols = {str(c).strip().lower(): c for c in raw.columns}
    missing = [n for n in ("date", "metric", "metric value") if n not in cols]
    if missing:
        raise ValueError("Missing column(s): " + ", ".join(missing) + ". Needed: Date, Metric, Metric Value.")
    d = pd.DataFrame({"date": pd.to_datetime(raw[cols["date"]], errors="coerce"),
                      "metric": raw[cols["metric"]].astype(str).str.strip(),
                      "value": pd.to_numeric(raw[cols["metric value"]], errors="coerce"),
                      "raw_value": raw[cols["metric value"]]})
    problems = []
    blank = d["raw_value"].isna() | (d["raw_value"].astype(str).str.strip() == "")
    if blank.sum():
        problems.append(f"{int(blank.sum())} blank value(s) skipped (treated as not submitted).")
    d = d[~blank]
    bad_date = d["date"].isna()
    if bad_date.sum():
        problems.append(f"{int(bad_date.sum())} row(s) with an unreadable date skipped.")
    d = d[~bad_date]
    valid = set(get_metrics(db)["metric"])
    unknown = ~d["metric"].isin(valid)
    if unknown.sum():
        names = ", ".join(sorted(d.loc[unknown, "metric"].unique())[:5])
        problems.append(f"{int(unknown.sum())} row(s) with an unknown metric skipped ({names}).")
    d = d[~unknown]
    bad_val = d["value"].isna() | (d["value"] < 0) | (d["value"] != d["value"].round())
    if bad_val.sum():
        problems.append(f"{int(bad_val.sum())} row(s) skipped: value is not a whole number of 0 or higher.")
    d = d[~bad_val]
    future = d["date"] > pd.Timestamp(date.today())
    if future.sum():
        problems.append(f"{int(future.sum())} row(s) dated after today. They are imported but check the dates.")
    dup = d.duplicated(["date", "metric"], keep="first")
    if dup.sum():
        problems.append(f"{int(dup.sum())} duplicate Date and Metric row(s) skipped. The first one is kept.")
    d = d[~dup]
    d = d.assign(date=d["date"].dt.strftime("%Y-%m-%d"))[["date", "metric", "value"]].reset_index(drop=True)
    return d, problems


def import_entries(db, branch_code, clean, username, chunk=500):
    """Save checked rows for one branch. Existing entries for the same date and metric are replaced."""
    if branch_code not in set(get_branches(db)["branch_code"]):
        raise ValueError("Unknown branch.")
    before = int(db.one("SELECT COUNT(*) FROM entries WHERE branch_code = ?", (branch_code,))[0])
    stamp = now()
    rows = [[branch_code, r[0], r[1], float(r[2]), stamp, username] for r in clean.values.tolist()]
    if not db.is_pg:
        chunk = 150
    one = "(?,?,?,?,?,?)"
    statements = []
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        statements.append((
            "INSERT INTO entries (branch_code, date, metric, value, updated_at, updated_by) VALUES "
            + ",".join([one] * len(part))
            + """ ON CONFLICT (branch_code, date, metric)
                 DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at,
                               updated_by = excluded.updated_by""",
            [v for r in part for v in r]))
    if statements:
        db.run(statements)
    after = int(db.one("SELECT COUNT(*) FROM entries WHERE branch_code = ?", (branch_code,))[0])
    added = after - before
    log(db, username, "import_entries", f"{branch_code}: {len(rows)} rows, {added} new, {len(rows) - added} replaced")
    return {"rows": len(rows), "added": added, "replaced": len(rows) - added}


def set_multiplier(db, metric, multiplier, username):
    old = db.one("SELECT multiplier FROM metrics WHERE metric = ?", (metric,))
    db.run([("UPDATE metrics SET multiplier = ? WHERE metric = ?", (float(multiplier), metric))])
    log(db, username, "set_multiplier", f"{metric}: {old[0] if old else None} -> {multiplier}")


# ---------------------------------------------------------------- calculations
def _between(df, start, end):
    return df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]


def ranking(df, start, end, branches=None):
    """Adjusted Value and rank per branch for a period. Branches with no data have no rank."""
    d = _between(df, start, end)
    g = d.groupby(["branch_code", "branch"], as_index=False).agg(
        adjusted=("adjusted", "sum"), metric_value=("value", "sum"),
        days_reported=("date", "nunique"), last_date=("date", "max"))
    if branches is not None:
        g = branches.merge(g, on=["branch_code", "branch"], how="left")
    elif "cluster" in d.columns:
        g = g.merge(d[["branch_code", "cluster"]].drop_duplicates(), on="branch_code", how="left")
    g["rank"] = g["adjusted"].rank(method="min", ascending=False)
    total = g["adjusted"].sum()
    g["share"] = g["adjusted"] / total if total else 0.0
    g["avg_per_day"] = g["adjusted"] / g["days_reported"]
    return g.sort_values(["rank", "branch"], na_position="last").reset_index(drop=True)


def quarter_bounds(day):
    day = pd.Timestamp(day)
    start = pd.Timestamp(year=day.year, month=3 * ((day.month - 1) // 3) + 1, day=1)
    return start, start + pd.offsets.QuarterEnd(0)


def quarter_label(day):
    day = pd.Timestamp(day)
    return f"Q{(day.month - 1) // 3 + 1} {day.year}"


def quarter_ranking(df, as_of, branches):
    """Quarter to date through as_of, for every branch.
    rank is across the whole program. cluster_rank is the position inside the branch's own cluster.
    prev_adjusted and prev_rank are for the full previous quarter."""
    as_of = pd.Timestamp(as_of)
    q_start, q_end = quarter_bounds(as_of)
    p_start, p_end = quarter_bounds(q_start - timedelta(days=1))
    cur = ranking(df, q_start, as_of, branches)
    cur["cluster_rank"] = cur.groupby("cluster")["adjusted"].rank(method="min", ascending=False)
    prev = ranking(df, p_start, p_end, branches)[["branch_code", "adjusted", "rank"]]
    prev = prev.rename(columns={"adjusted": "prev_adjusted", "rank": "prev_rank"})
    out = cur.merge(prev, on="branch_code", how="left")
    out["rank_change"] = out["prev_rank"] - out["rank"]
    months = _between(df, q_start, as_of).copy()
    if len(months):
        months["month"] = months["date"].dt.strftime("%b")
        order = list(dict.fromkeys(months.sort_values("date")["month"]))
        piv = months.pivot_table(index="branch_code", columns="month", values="adjusted", aggfunc="sum")[order]
        out = out.merge(piv.reset_index(), on="branch_code", how="left")
    else:
        order = []
    info = {"label": quarter_label(as_of), "start": q_start, "end": as_of, "quarter_end": q_end,
            "prev_label": quarter_label(p_start), "months": order,
            "ranked": int(out["rank"].notna().sum()), "branches": len(out)}
    return out, info


def cluster_summary(table):
    """One row per cluster from a quarter_ranking table."""
    g = table.groupby("cluster", as_index=False).agg(
        branches=("branch_code", "count"), reporting=("rank", "count"),
        adjusted=("adjusted", "sum"), best_rank=("rank", "min"))
    g["avg_per_branch"] = g["adjusted"] / g["reporting"].where(g["reporting"] > 0)
    g.loc[g["reporting"] == 0, "adjusted"] = float("nan")
    g["cluster_rank"] = g["adjusted"].rank(method="min", ascending=False)
    total = g["adjusted"].sum()
    g["share"] = g["adjusted"] / total if total else 0.0
    top = table.dropna(subset=["rank"]).sort_values("rank").groupby("cluster")["branch"].first()
    g["top_branch"] = g["cluster"].map(top)
    return g.sort_values(["cluster_rank", "cluster"], na_position="last").reset_index(drop=True)


def cluster_view(table, cluster):
    """The branches of one cluster, with their program rank and their rank inside the cluster."""
    return table[table["cluster"] == cluster].sort_values(["rank", "branch"], na_position="last").reset_index(drop=True)


def month_bounds(day):
    day = pd.Timestamp(day)
    start = day.replace(day=1)
    return start, start + pd.offsets.MonthEnd(0)


def mtd_compare(df, as_of, branches=None):
    """Month to date through as_of, against the previous month up to the same day number."""
    as_of = pd.Timestamp(as_of)
    cur_start, _ = month_bounds(as_of)
    prev_start = cur_start - pd.offsets.MonthBegin(1)
    prev_last = cur_start - timedelta(days=1)
    prev_end = min(prev_start + timedelta(days=as_of.day - 1), prev_last)
    cur = ranking(df, cur_start, as_of, branches)
    prev = ranking(df, prev_start, prev_end, branches)[["branch_code", "adjusted", "rank"]]
    prev = prev.rename(columns={"adjusted": "prev_adjusted", "rank": "prev_rank"})
    out = cur.merge(prev, on="branch_code", how="left")
    out["rank_change"] = out["prev_rank"] - out["rank"]          # positive = moved up
    out["change_pct"] = (out["adjusted"] - out["prev_adjusted"]) / out["prev_adjusted"]
    info = {"cur_start": cur_start, "cur_end": as_of, "prev_start": prev_start, "prev_end": prev_end,
            "cur_total": float(out["adjusted"].sum()), "prev_total": float(out["prev_adjusted"].sum())}
    info["change_pct"] = (info["cur_total"] - info["prev_total"]) / info["prev_total"] if info["prev_total"] else None
    return out, info


def daily_breakdown(df, start, end, branch_code=None):
    d = _between(df, start, end)
    if branch_code:
        d = d[d["branch_code"] == branch_code]
    g = d.groupby("date", as_index=False)["adjusted"].sum().sort_values("date")
    g["running_total"] = g["adjusted"].cumsum()
    return g


def metric_breakdown(df, start, end, branch_code=None):
    d = _between(df, start, end)
    if branch_code:
        d = d[d["branch_code"] == branch_code]
    g = d.groupby(["metric", "multiplier"], as_index=False).agg(
        metric_value=("value", "sum"), adjusted=("adjusted", "sum"))
    total = g["adjusted"].sum()
    g["share"] = g["adjusted"] / total if total else 0.0
    return g.sort_values("adjusted", ascending=False).reset_index(drop=True)


def submission_check(db, day):
    """One row per branch: Submitted, Partial or Not submitted for the day. Counts active metrics only."""
    n_metrics = int(db.one("SELECT COUNT(*) FROM metrics WHERE active = 1")[0])
    df = db.query(
        """SELECT b.branch_code, b.branch, COUNT(m.metric) AS entered
           FROM branches b
           LEFT JOIN entries e ON e.branch_code = b.branch_code AND e.date = ?
           LEFT JOIN metrics m ON m.metric = e.metric AND m.active = 1
           GROUP BY b.branch_code, b.branch ORDER BY b.branch_code""", (str(day),))
    df["entered"] = df["entered"].astype(int)
    df["expected"] = n_metrics
    df["status"] = df["entered"].map(
        lambda n: "Submitted" if n >= n_metrics else ("Not submitted" if n == 0 else "Partial"))
    return df


def data_quality(db):
    """Per branch: first and last date, days reported, and a status."""
    df = db.query(
        """SELECT b.branch_code, b.branch, MIN(e.date) AS first_date, MAX(e.date) AS last_date,
                  COUNT(DISTINCT e.date) AS days_reported, COUNT(e.metric) AS entries
           FROM branches b LEFT JOIN entries e ON e.branch_code = b.branch_code
           GROUP BY b.branch_code, b.branch ORDER BY b.branch_code""")
    for c in ("first_date", "last_date"):
        df[c] = df[c].map(lambda v: None if v is None or pd.isna(v) else str(v)[:10]).astype(object)
    known = df["last_date"].dropna()
    latest = known.max() if len(known) else None
    n_metrics = int(db.one("SELECT COUNT(*) FROM metrics WHERE active = 1")[0])
    partial = db.query(
        """SELECT branch_code, COUNT(*) AS partial_days FROM
           (SELECT e.branch_code, e.date FROM entries e
            JOIN metrics m ON m.metric = e.metric AND m.active = 1
            GROUP BY e.branch_code, e.date HAVING COUNT(*) < ?) p
           GROUP BY branch_code""", (n_metrics,))
    df = df.merge(partial, on="branch_code", how="left")
    df["partial_days"] = df["partial_days"].fillna(0).astype(int)

    def status(r):
        if r["last_date"] is None or pd.isna(r["last_date"]):
            return "No data"
        if r["last_date"] < latest:
            return "Behind"
        if r["partial_days"] > 0:
            return "Partial days"
        return "OK"

    df["status"] = df.apply(status, axis=1)
    return df


def last_working_day(today=None):
    d = pd.Timestamp(today or date.today())
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.date()


def latest_data_date(df, today=None):
    """Latest date with data that is not after today."""
    today = pd.Timestamp(today or date.today())
    d = df.loc[df["date"] <= today, "date"]
    return d.max().date() if len(d) else today.date()
