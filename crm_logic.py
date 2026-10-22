"""CRM for the company portal: clients, call-backs, random assignment, notifications and the link to Branch KPI.

No Streamlit code in this file, so it can be tested on its own.

Tables:
  clients        one row per client: details, branch, status, who it is assigned to, last contact
  crm_contacts   every contact made: who, when, the outcome and a note
  crm_calls      the call-back list: which client, who calls, on what date, done or pending
  notifications  short messages shown on a person's Home page
Rules:
  A client that is not closed can get a call-back date. That adds a row to the call-back list for the person
  who will call. Logging a contact closes that person's pending call-backs for the client.
  "Untouched" clients are New, never contacted. The randomizer shares them out evenly at random.
  When someone contacts a client that another person contacted in the last few days, that other person is
  told, so two people do not call the same client unknowingly.
  Branch KPI link: contacts (or closed sales) per branch per day can be counted for one KPI metric. The count
  can either fill that metric's entries ("fill") or be shown next to what branches typed ("validate").
"""
import random
import re
import secrets
from datetime import date, timedelta

import pandas as pd

import att_logic as a
import hr_logic as h
import kpi_logic as k

STATUSES = ("New", "Contacted", "Interested", "Call back", "Closed won", "Closed lost")
CLOSED = ("Closed won", "Closed lost")
RECENT_DAYS = 7
CLIENT_COLUMNS = ["Name", "Company", "Phone", "Email", "Branch", "Source", "Notes"]


def _schema(is_pg):
    return [
        """CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, company TEXT, phone TEXT, email TEXT, branch_code TEXT,
            source TEXT, notes TEXT, status TEXT NOT NULL DEFAULT 'New', assigned_to TEXT,
            created_by TEXT, created_at TEXT, last_contact_at TEXT, last_contact_by TEXT, next_call_on TEXT)""",
        """CREATE TABLE IF NOT EXISTS crm_contacts (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL, username TEXT NOT NULL, at TEXT NOT NULL,
            contact_date TEXT NOT NULL, outcome TEXT NOT NULL, note TEXT)""",
        """CREATE TABLE IF NOT EXISTS crm_calls (
            id TEXT PRIMARY KEY, client_id TEXT NOT NULL, assigned_to TEXT NOT NULL, call_on TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending', created_by TEXT, created_at TEXT, done_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY, username TEXT NOT NULL, at TEXT NOT NULL, message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS idx_contacts_date ON crm_contacts (contact_date)",
        "CREATE INDEX IF NOT EXISTS idx_calls_user ON crm_calls (assigned_to, status)",
    ]


def init_crm(db):
    db.run([(s, ()) for s in _schema(db.is_pg)])


# ---------------------------------------------------------------- notifications
def notify(db, username, message):
    db.run([("INSERT INTO notifications (id, username, at, message, is_read) VALUES (?,?,?,?,0)",
             (secrets.token_hex(8), username, k.now(), message))])


def my_notifications(db, username, unread_only=True, limit=30):
    df = db.query("SELECT id, at, message, is_read FROM notifications WHERE username = ?" +
                  (" AND is_read = 0" if unread_only else "") + f" ORDER BY at DESC LIMIT {int(limit)}", (username,))
    df["is_read"] = df["is_read"].astype(int)
    return df


def mark_read(db, username, ids=None):
    if ids is None:
        db.run([("UPDATE notifications SET is_read = 1 WHERE username = ?", (username,))])
    else:
        db.run([("UPDATE notifications SET is_read = 1 WHERE username = ? AND id = ?", (username, i)) for i in ids])


# ---------------------------------------------------------------- clients
def _clean_phone(p):
    return re.sub(r"[^0-9+]", "", p or "")


def add_client(db, by, name, company=None, phone=None, email=None, branch_code=None, source=None, notes=None,
               assigned_to=None, check_duplicates=True):
    name = (name or "").strip()
    if not name:
        raise ValueError("Enter the client's name.")
    phone = (phone or "").strip() or None
    email = (email or "").strip().lower() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError(f"{email} is not a valid email address.")
    if not phone and not email:
        raise ValueError("Enter a phone number or an email address.")
    branch_code = (branch_code or "").strip() or None
    if branch_code and not db.one("SELECT COUNT(*) FROM branches WHERE branch_code = ?", (branch_code,))[0]:
        raise ValueError(f"{branch_code} is not in the branch list.")
    if check_duplicates:
        dup = find_duplicate(db, phone, email)
        if dup:
            raise ValueError(f"A client with this phone or email already exists: {dup}.")
    cid = secrets.token_hex(6)
    db.run([("""INSERT INTO clients (id, name, company, phone, email, branch_code, source, notes, status, assigned_to,
                created_by, created_at) VALUES (?,?,?,?,?,?,?,?,'New',?,?,?)""",
             (cid, name, (company or "").strip() or None, phone, email, branch_code, (source or "").strip() or None,
              (notes or "").strip() or None, assigned_to, by, k.now()))])
    k.log(db, by, "add_client", name)
    return cid


def find_duplicate(db, phone, email):
    if phone:
        p = _clean_phone(phone)
        rows = db.query("SELECT name, phone FROM clients WHERE phone IS NOT NULL")
        for n, ph in zip(rows["name"], rows["phone"]):
            if _clean_phone(ph) == p and p:
                return n
    if email:
        row = db.one("SELECT name FROM clients WHERE email = ?", (email.strip().lower(),))
        if row:
            return row[0]
    return None


def bulk_clients(db, table, by, default_branch=None):
    """Load clients from a table with CLIENT_COLUMNS. Duplicates (same phone or email) are skipped."""
    cols = {str(c).strip().lower(): c for c in table.columns}
    if "name" not in cols:
        raise ValueError("Missing column: Name")
    added, skipped = [], []
    for i, r in table.iterrows():
        def cell(n):
            c = cols.get(n.lower())
            v = r[c] if c is not None else None
            return "" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v).strip()
        if not cell("Name"):
            continue
        try:
            add_client(db, by, cell("Name"), cell("Company"), cell("Phone"), cell("Email"),
                       cell("Branch") or default_branch, cell("Source"), cell("Notes"))
            added.append(cell("Name"))
        except ValueError as err:
            skipped.append({"Row": i + 2, "Name": cell("Name"), "Reason": str(err)})
    k.log(db, by, "bulk_clients", f"{len(added)} added, {len(skipped)} skipped")
    return len(added), pd.DataFrame(skipped, columns=["Row", "Name", "Reason"])


def update_client(db, cid, by, **fields):
    allowed = {"name", "company", "phone", "email", "branch_code", "source", "notes", "assigned_to", "status"}
    sets, vals = [], []
    for key, v in fields.items():
        if key not in allowed:
            raise ValueError(f"Unknown field {key}.")
        if key == "status" and v not in STATUSES:
            raise ValueError("Unknown status.")
        sets.append(f"{key} = ?"); vals.append((v.strip() if isinstance(v, str) else v) or None)
    if sets:
        db.run([(f"UPDATE clients SET {', '.join(sets)} WHERE id = ?", vals + [cid])])
        k.log(db, by, "update_client", cid)


def clients(db, branch_code=None, assigned_to=None, status=None, search=None):
    sql = """SELECT c.id, c.name, c.company, c.phone, c.email, c.branch_code, c.source, c.status, c.assigned_to,
                    u.full_name AS assigned_name, c.last_contact_at, c.last_contact_by, c.next_call_on, c.notes, c.created_at
             FROM clients c LEFT JOIN users u ON u.username = c.assigned_to"""
    where, params = [], []
    if branch_code:
        where.append("c.branch_code = ?"); params.append(branch_code)
    if assigned_to:
        where.append("c.assigned_to = ?"); params.append(assigned_to)
    if status:
        where.append("c.status = ?"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    df = db.query(sql + " ORDER BY c.created_at DESC", params)
    if search:
        s = search.strip().lower()
        mask = df[["name", "company", "phone", "email"]].fillna("").apply(lambda r: s in " ".join(r).lower(), axis=1)
        df = df[mask] if len(df) else df
    return df.reset_index(drop=True)


def untouched(db, branch_code=None, include_assigned=False):
    """Clients still New and never contacted. By default only the unassigned ones."""
    df = clients(db, branch_code=branch_code, status="New")
    df = df[df["last_contact_at"].isna()]
    if not include_assigned:
        df = df[df["assigned_to"].isna()]
    return df.reset_index(drop=True)


def assign_random(db, usernames, by, client_ids=None, branch_code=None, include_assigned=False, seed=None):
    """Share untouched clients out at random and evenly. Returns {username: count}."""
    usernames = [u for u in dict.fromkeys(usernames) if u]
    if not usernames:
        raise ValueError("Pick at least one person to assign clients to.")
    pool = untouched(db, branch_code, include_assigned)
    if client_ids is not None:
        pool = pool[pool["id"].isin(list(client_ids))]
    ids = list(pool["id"])
    if not ids:
        raise ValueError("There are no untouched clients to assign.")
    rng = random.Random(seed)
    rng.shuffle(ids)
    people = usernames[:]
    rng.shuffle(people)
    counts = {u: 0 for u in usernames}
    stmts = []
    for i, cid in enumerate(ids):
        u = people[i % len(people)]
        counts[u] += 1
        stmts.append(("UPDATE clients SET assigned_to = ? WHERE id = ?", (u, cid)))
    db.run(stmts)
    for u, n in counts.items():
        if n:
            notify(db, u, f"{n} new client(s) were assigned to you by {by}.")
    k.log(db, by, "assign_random", ", ".join(f"{u}: {n}" for u, n in counts.items()))
    return counts


# ---------------------------------------------------------------- contacts and call-backs
def log_contact(db, cid, username, outcome, note="", call_again_on=None, call_again_by=None, contact_date=None):
    """Record a contact. Sets the client's status and last contact. Closes this person's pending call-backs
    for the client. If the client is not closed and a call-back date is given, adds a call-back.
    Returns a list of warnings (for example, someone else contacted this client recently)."""
    if outcome not in STATUSES or outcome == "New":
        raise ValueError("Pick the outcome of the contact.")
    row = db.one("SELECT name, last_contact_at, last_contact_by, branch_code FROM clients WHERE id = ?", (cid,))
    if not row:
        raise ValueError("Client not found.")
    name, last_at, last_by, _ = row
    cdate = pd.Timestamp(contact_date).date() if contact_date else a.local_today()
    if call_again_on:
        call_again_on = pd.Timestamp(call_again_on).date()
        if outcome in CLOSED:
            raise ValueError("A closed client does not need a call-back.")
        if call_again_on < cdate:
            raise ValueError("The call-back date must be today or later.")
    warnings = []
    if last_by and last_by != username and last_at:
        days = (pd.Timestamp(k.now()) - pd.Timestamp(last_at)).days
        if days <= RECENT_DAYS:
            warnings.append(f"{last_by} contacted {name} {days} day(s) ago.")
            notify(db, last_by, f"{username} also contacted {name}, which you contacted on {str(last_at)[:10]}.")
    stamp = k.now()
    stmts = [("""INSERT INTO crm_contacts (id, client_id, username, at, contact_date, outcome, note)
                 VALUES (?,?,?,?,?,?,?)""", (secrets.token_hex(8), cid, username, stamp, str(cdate), outcome, (note or "").strip())),
             ("UPDATE crm_calls SET status = 'Done', done_at = ? WHERE client_id = ? AND status = 'Pending' AND assigned_to = ?",
              (stamp, cid, username))]
    status = "Call back" if (call_again_on and outcome not in CLOSED and outcome != "Interested") else outcome
    stmts.append(("UPDATE clients SET status = ?, last_contact_at = ?, last_contact_by = ?, next_call_on = ? WHERE id = ?",
                  (status, stamp, username, str(call_again_on) if call_again_on else None, cid)))
    if outcome in CLOSED:
        stmts.append(("UPDATE crm_calls SET status = 'Cancelled' WHERE client_id = ? AND status = 'Pending'", (cid,)))
    if call_again_on:
        who = call_again_by or username
        stmts.append(("""INSERT INTO crm_calls (id, client_id, assigned_to, call_on, status, created_by, created_at)
                         VALUES (?,?,?,?,'Pending',?,?)""", (secrets.token_hex(8), cid, who, str(call_again_on), username, stamp)))
    db.run(stmts)
    if call_again_on and (call_again_by or username) != username:
        notify(db, call_again_by, f"{username} asked you to call {name} on {call_again_on:%d %b %Y}.")
    k.log(db, username, "log_contact", f"{name}: {outcome}")
    return warnings


def contacts(db, cid=None, start=None, end=None, username=None):
    sql = """SELECT t.id, t.client_id, c.name AS client, c.branch_code, t.username, t.at, t.contact_date, t.outcome, t.note
             FROM crm_contacts t JOIN clients c ON c.id = t.client_id"""
    where, params = [], []
    if cid:
        where.append("t.client_id = ?"); params.append(cid)
    if start:
        where.append("t.contact_date >= ?"); params.append(str(start))
    if end:
        where.append("t.contact_date <= ?"); params.append(str(end))
    if username:
        where.append("t.username = ?"); params.append(username)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return db.query(sql + " ORDER BY t.at DESC", params)


def call_list(db, username=None, status="Pending", due_by=None, branch_code=None):
    """The call-back table: who calls which client when."""
    sql = """SELECT l.id, l.client_id, c.name AS client, c.company, c.phone, c.email, c.branch_code, c.status AS client_status,
                    l.assigned_to, u.full_name AS assigned_name, l.call_on, l.status, l.created_by
             FROM crm_calls l JOIN clients c ON c.id = l.client_id LEFT JOIN users u ON u.username = l.assigned_to"""
    where, params = [], []
    if username:
        where.append("l.assigned_to = ?"); params.append(username)
    if status:
        where.append("l.status = ?"); params.append(status)
    if due_by:
        where.append("l.call_on <= ?"); params.append(str(due_by))
    if branch_code:
        where.append("c.branch_code = ?"); params.append(branch_code)
    if where:
        sql += " WHERE " + " AND ".join(where)
    return db.query(sql + " ORDER BY l.call_on, c.name", params)


def reassign_call(db, call_id, new_user, by):
    row = db.one("SELECT c.name, l.call_on FROM crm_calls l JOIN clients c ON c.id = l.client_id WHERE l.id = ?", (call_id,))
    if not row:
        raise ValueError("Call-back not found.")
    db.run([("UPDATE crm_calls SET assigned_to = ? WHERE id = ? AND status = 'Pending'", (new_user, call_id))])
    notify(db, new_user, f"{by} gave you a call-back: {row[0]} on {row[1]}.")
    k.log(db, by, "reassign_call", f"{row[0]} -> {new_user}")


def due_reminders(db, username, today=None):
    """Create one reminder per due call-back that has not been reminded today. Returns how many were added."""
    today = pd.Timestamp(today or a.local_today()).date()
    due = call_list(db, username, "Pending", today)
    if due.empty:
        return 0
    sent = my_notifications(db, username, unread_only=False, limit=200)
    sent_today = set(m for m, t in zip(sent["message"], sent["at"]) if str(t)[:10] == str(today))
    n = 0
    for _, r in due.iterrows():
        msg = f"Call-back due: {r['client']} ({r['call_on']})."
        if msg not in sent_today:
            notify(db, username, msg)
            n += 1
    return n


# ---------------------------------------------------------------- link to Branch KPI
def kpi_link(db):
    """The CRM to KPI setting: metric name (or None), what is counted, and the mode."""
    return {"metric": h.get_setting(db, "crm_kpi_metric") or None,
            "count": h.get_setting(db, "crm_kpi_count", "contacts"),
            "mode": h.get_setting(db, "crm_kpi_mode", "validate")}


def set_kpi_link(db, metric, count, mode, by):
    if metric and metric not in set(k.get_metrics(db)["metric"]):
        raise ValueError(f"{metric} is not a Branch KPI metric.")
    if count not in ("contacts", "closed_won"):
        raise ValueError("Count must be contacts or closed_won.")
    if mode not in ("validate", "fill"):
        raise ValueError("Mode must be validate or fill.")
    h.set_setting(db, "crm_kpi_metric", metric or "", by)
    h.set_setting(db, "crm_kpi_count", count, by)
    h.set_setting(db, "crm_kpi_mode", mode, by)


def crm_counts(db, start, end, count="contacts"):
    """Per branch per date: number of contacts made (or closed won). Branch = the client's branch,
    else the branch of the person who made the contact."""
    df = contacts(db, start=start, end=end)
    if count == "closed_won":
        df = df[df["outcome"] == "Closed won"]
    if df.empty:
        return pd.DataFrame(columns=["branch_code", "date", "crm_count"])
    ub = db.query("SELECT username, branch_code AS user_branch FROM users")
    df = df.merge(ub, on="username", how="left")
    df["branch_code"] = df["branch_code"].fillna(df["user_branch"])
    df = df[df["branch_code"].notna()]
    g = df.groupby(["branch_code", "contact_date"]).size().reset_index(name="crm_count")
    return g.rename(columns={"contact_date": "date"})


def validation(db, start, end):
    """CRM count next to what each branch entered for the linked metric, per branch and date."""
    link = kpi_link(db)
    if not link["metric"]:
        raise ValueError("No Branch KPI metric is linked to the CRM yet.")
    c = crm_counts(db, start, end, link["count"])
    e = db.query("SELECT branch_code, date, value FROM entries WHERE metric = ? AND date >= ? AND date <= ?",
                 (link["metric"], str(start), str(end)))
    e["date"] = e["date"].astype(str).str[:10]
    e["value"] = e["value"].astype(float)
    out = c.merge(e, on=["branch_code", "date"], how="outer")
    out["crm_count"] = out["crm_count"].fillna(0).astype(int)
    out["difference"] = out["value"] - out["crm_count"]
    out["check"] = ["Not entered" if pd.isna(v) else ("Matches" if d == 0 else ("Higher than CRM" if d > 0 else "Lower than CRM"))
                    for v, d in zip(out["value"], out["difference"])]
    return out.sort_values(["date", "branch_code"]).reset_index(drop=True)


def fill_kpi(db, start, end, by, overwrite=False):
    """Write the CRM counts into the linked metric's entries. Existing entries are kept unless overwrite."""
    link = kpi_link(db)
    if not link["metric"]:
        raise ValueError("No Branch KPI metric is linked to the CRM yet.")
    c = crm_counts(db, start, end, link["count"])
    existing = db.query("SELECT branch_code, date FROM entries WHERE metric = ? AND date >= ? AND date <= ?",
                        (link["metric"], str(start), str(end)))
    have = set(zip(existing["branch_code"], existing["date"].astype(str).str[:10]))
    stamp = k.now()
    stmts, n = [], 0
    for _, r in c.iterrows():
        key = (r["branch_code"], r["date"])
        if key in have and not overwrite:
            continue
        stmts.append(("DELETE FROM entries WHERE branch_code = ? AND date = ? AND metric = ?", (key[0], key[1], link["metric"])))
        stmts.append(("""INSERT INTO entries (branch_code, date, metric, value, updated_at, updated_by)
                         VALUES (?,?,?,?,?,?)""", (key[0], key[1], link["metric"], float(r["crm_count"]), stamp, "crm")))
        n += 1
    if stmts:
        db.run(stmts)
    k.log(db, by, "fill_kpi_from_crm", f"{link['metric']}: {n} entries")
    return n


def branch_achievement(db, month):
    """For the linked metric: CRM count per branch for the month against the branch target, if set."""
    link = kpi_link(db)
    if not link["metric"]:
        raise ValueError("No Branch KPI metric is linked to the CRM yet.")
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise ValueError("Month must look like 2026-10.")
    start = pd.Timestamp(month + "-01").date()
    end = (pd.Timestamp(start) + pd.offsets.MonthEnd(0)).date()
    c = crm_counts(db, start, end, link["count"]).groupby("branch_code", as_index=False)["crm_count"].sum()
    t = db.query("SELECT branch_code, target FROM kpi_targets WHERE metric = ? AND month = ?", (link["metric"], month))
    t["target"] = t["target"].astype(float)
    b = k.get_branches(db)[["branch_code", "branch"]]
    out = b.merge(c, on="branch_code", how="left").merge(t, on="branch_code", how="left")
    out["crm_count"] = out["crm_count"].fillna(0).astype(int)
    out["pct"] = [cnt / tg * 100 if tg and not pd.isna(tg) else None for cnt, tg in zip(out["crm_count"], out["target"])]
    out["rank"] = out["crm_count"].rank(method="min", ascending=False).astype(int)
    return out.sort_values(["rank", "branch_code"]).reset_index(drop=True)
