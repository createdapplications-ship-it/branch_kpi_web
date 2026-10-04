"""Attendance rules for the company portal. Uses the same database and the same user accounts as Branch KPI.

No Streamlit code in this file, so it can be tested on its own.
Rules:
  Time In opens a record. Time Out closes it. One open record per person at a time.
  A person can time in and out more than once a day (for example around a break). Hours are added up.
  Times are stored in UTC and shown in the app time zone. The work date is the local date at Time In.
  A record still open after MAX_SHIFT_HOURS is flagged "No time out". Only the owner can correct it.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import kpi_logic as k

MAX_SHIFT_HOURS = 16
TZ_NAME = os.environ.get("APP_TIMEZONE", "Asia/Manila")


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_local(utc_text, tz=None):
    """UTC text from the database to a local datetime, or None."""
    if utc_text is None or pd.isna(utc_text) or utc_text == "":
        return None
    d = datetime.fromisoformat(str(utc_text)).replace(tzinfo=timezone.utc)
    return d.astimezone(ZoneInfo(tz or TZ_NAME)).replace(tzinfo=None)


def to_utc(local_dt, tz=None):
    return local_dt.replace(tzinfo=ZoneInfo(tz or TZ_NAME)).astimezone(timezone.utc).replace(tzinfo=None)


def local_today(tz=None):
    return to_local(utc_now().isoformat(), tz).date()


# ---------------------------------------------------------------- attendance
def open_record(db, username):
    """The person's open record (timed in, not yet out), or None."""
    row = db.one("""SELECT id, work_date, time_in FROM att_records
                    WHERE username = ? AND time_out IS NULL ORDER BY time_in DESC LIMIT 1""", (username,))
    return None if not row else {"id": row[0], "work_date": row[1], "time_in": row[2]}


def _stale(rec, at):
    return (at - datetime.fromisoformat(rec["time_in"])) > timedelta(hours=MAX_SHIFT_HOURS)


def status(db, username, at=None):
    """'in', 'out' or 'no_time_out' (an old record was never closed)."""
    at = at or utc_now()
    rec = open_record(db, username)
    if not rec:
        return "out", None
    return ("no_time_out" if _stale(rec, at) else "in"), rec


def time_in(db, username, at=None, tz=None):
    at = (at or utc_now()).replace(microsecond=0)
    state, rec = status(db, username, at)
    if state == "in":
        raise ValueError("You are already timed in. Time out first.")
    rid = secrets.token_hex(8)
    work_date = str(to_local(at.isoformat(), tz).date())
    db.run([("INSERT INTO att_records (id, username, work_date, time_in) VALUES (?,?,?,?)",
             (rid, username, work_date, at.isoformat()))])
    k.log(db, username, "time_in", work_date)
    return rid


def time_out(db, username, at=None):
    at = (at or utc_now()).replace(microsecond=0)
    state, rec = status(db, username, at)
    if state == "out":
        raise ValueError("You are not timed in.")
    if state == "no_time_out":
        raise ValueError(f"Your time in on {rec['work_date']} was never closed. Ask the owner to correct it, "
                         "then time in again.")
    if at < datetime.fromisoformat(rec["time_in"]):
        raise ValueError("Time out must be after time in.")
    db.run([("UPDATE att_records SET time_out = ? WHERE id = ? AND time_out IS NULL", (at.isoformat(), rec["id"]))])
    k.log(db, username, "time_out", rec["work_date"])
    return rec["id"]


def records(db, start, end, username=None, tz=None, at=None):
    """Records for a date range with local times, hours and a status."""
    sql = """SELECT r.id, r.username, u.full_name, u.branch_code, r.work_date, r.time_in, r.time_out, r.note, r.edited_by
             FROM att_records r JOIN users u ON u.username = r.username
             WHERE r.work_date >= ? AND r.work_date <= ?"""
    params = [str(start), str(end)]
    if username:
        sql += " AND r.username = ?"
        params.append(username)
    df = db.query(sql + " ORDER BY r.work_date, r.time_in", params)
    at = at or utc_now()
    df["in_local"] = [to_local(v, tz) for v in df["time_in"]]
    df["out_local"] = [to_local(v, tz) for v in df["time_out"]]
    hours, state = [], []
    for ti, to in zip(df["time_in"], df["time_out"]):
        if to is None or pd.isna(to):
            hours.append(float("nan"))
            state.append("No time out" if at - datetime.fromisoformat(ti) > timedelta(hours=MAX_SHIFT_HOURS) else "In")
        else:
            hours.append((datetime.fromisoformat(to) - datetime.fromisoformat(ti)).total_seconds() / 3600)
            state.append("Complete")
    df["hours"] = pd.Series(hours, dtype=float)
    df["status"] = pd.Series(state, dtype=object)
    return df


def today_board(db, day=None, tz=None, at=None):
    """One row per active person for a day: In, Out or Not in, first time in, last time out, hours."""
    day = str(day or local_today(tz))
    users = db.query("""SELECT username, full_name, role, branch_code FROM users
                        WHERE active = 1 ORDER BY branch_code, full_name""")
    r = records(db, day, day, tz=tz, at=at)
    rows = []
    for _, u in users.iterrows():
        mine = r[r["username"] == u["username"]]
        if mine.empty:
            rows.append(("Not in", None, None, float("nan")))
            continue
        is_in = mine["time_out"].isna().any()
        outs = mine["out_local"].dropna()
        rows.append(("In" if is_in else "Out", mine["in_local"].min(),
                     None if is_in or outs.empty else outs.max(), mine["hours"].sum(min_count=1)))
    extra = pd.DataFrame(rows, columns=["status", "first_in", "last_out", "hours"], index=users.index)
    return pd.concat([users, extra], axis=1)


def report(db, start, end, tz=None, at=None):
    """One row per active person for a date range: days present, hours, records with no time out."""
    users = db.query("""SELECT username, full_name, role, branch_code FROM users
                        WHERE active = 1 ORDER BY branch_code, full_name""")
    r = records(db, start, end, tz=tz, at=at)
    g = r.groupby("username").agg(days_present=("work_date", "nunique"), hours=("hours", "sum"),
                                  no_time_out=("status", lambda s: int((s == "No time out").sum()))).reset_index()
    out = users.merge(g, on="username", how="left")
    for c in ("days_present", "no_time_out"):
        out[c] = out[c].fillna(0).astype(int)
    out["hours"] = out["hours"].fillna(0.0)
    out["avg_hours"] = (out["hours"] / out["days_present"]).where(out["days_present"] > 0)
    return out


def correct_record(db, record_id, time_in_local, time_out_local, reason, by, tz=None):
    """Owner action. Set the time in and time out of a record (local times). A reason is required."""
    if not (reason or "").strip():
        raise ValueError("Enter a reason for the correction.")
    row = db.one("SELECT username, time_in, time_out FROM att_records WHERE id = ?", (record_id,))
    if not row:
        raise ValueError("Record not found.")
    if time_out_local is not None and time_out_local <= time_in_local:
        raise ValueError("Time out must be after time in.")
    ti = to_utc(time_in_local, tz).isoformat()
    to = to_utc(time_out_local, tz).isoformat() if time_out_local is not None else None
    db.run([("UPDATE att_records SET time_in = ?, time_out = ?, work_date = ?, note = ?, edited_by = ? WHERE id = ?",
             (ti, to, str(time_in_local.date()), reason.strip(), by, record_id))])
    k.log(db, by, "correct_record", f"{row[0]} {record_id}: {row[1]} / {row[2]} -> {ti} / {to}. {reason.strip()}")


def add_record(db, username, time_in_local, time_out_local, reason, by, tz=None):
    """Owner action. Add a record for a person who did not time in. A reason is required."""
    if not (reason or "").strip():
        raise ValueError("Enter a reason for the correction.")
    if not db.one("SELECT COUNT(*) FROM users WHERE username = ?", (username,))[0]:
        raise ValueError("User not found.")
    if time_out_local is None or time_out_local <= time_in_local:
        raise ValueError("Time out must be after time in.")
    rid = secrets.token_hex(8)
    db.run([("""INSERT INTO att_records (id, username, work_date, time_in, time_out, note, edited_by)
                VALUES (?,?,?,?,?,?,?)""",
             (rid, username, str(time_in_local.date()), to_utc(time_in_local, tz).isoformat(),
              to_utc(time_out_local, tz).isoformat(), reason.strip(), by))])
    k.log(db, by, "add_record", f"{username} {time_in_local} to {time_out_local}. {reason.strip()}")
    return rid
