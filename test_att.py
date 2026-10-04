"""Checks the attendance rules and the shared accounts.
Run: python test_att.py
Uses a temporary SQLite file, or PostgreSQL when DATABASE_URL is set (use an empty test database)."""
import os, tempfile
from datetime import datetime, timedelta
import pandas as pd
os.environ.setdefault("KPI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
import kpi_logic as k
import att_logic as a

db = k.connect()
print("Backend:", "PostgreSQL" if db.is_pg else "SQLite")
k.init_db(db, "owner", "Start1234", load_sample=False)
res = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name); res.append(bool(cond))
def raises(name, fn):
    try: fn(); ok(name, False)
    except ValueError: ok(name, True)

TZ = "Asia/Manila"
# accounts: one list for both parts
k.create_user(db, "juan", "Juan Cruz", "employee", "Branch01", "Abcd1234", by="owner")
k.create_user(db, "maria", "Maria Santos", "employee", None, "Abcd1234", by="owner")
k.create_user(db, "enc01", "Encoder 01", "branch", "Branch01", "Abcd1234", by="owner")
ok("an employee account signs in with the shared account list", k.check_login(db, "juan", "Abcd1234")["role"] == "employee")
raises("the branch role still needs a branch", lambda: k.create_user(db, "nb", "X", "branch", None, "Abcd1234", by="owner"))
raises("a branch that does not exist is refused", lambda: k.create_user(db, "nb", "X", "employee", "Branch99", "Abcd1234", by="owner"))
raises("an unknown role is refused", lambda: k.create_user(db, "nb", "X", "staff", None, "Abcd1234", by="owner"))

# 65 users from a file
rows = [{"Username": f"emp{i:02d}", "Full Name": f"Employee {i:02d}", "Role": "employee", "Branch": f"Branch{(i % 20) + 1:02d}"} for i in range(1, 61)]
rows += [{"Username": f"mgr{i}", "Full Name": f"Manager {i}", "Role": "manager", "Branch": ""} for i in range(1, 6)]
created, problems = k.bulk_create_users(db, pd.DataFrame(rows), by="owner")
ok("65 users are created from one file, each with a temporary password", len(created) == 65 and len(problems) == 0 and created["Temporary Password"].nunique() == 65)
u = k.check_login(db, "emp07", created.set_index("Username").loc["emp07", "Temporary Password"])
ok("a user from the file signs in and must change the password", u is not None and u["must_change"])
c2, p2 = k.bulk_create_users(db, pd.DataFrame(rows[:2] + [{"Username": "new.one", "Full Name": "New One", "Role": "employee", "Branch": "Branch99"}]), by="owner")
ok("loading the file again skips existing users and reports each problem", len(c2) == 0 and len(p2) == 3)
raises("a file with a missing column is refused", lambda: k.bulk_create_users(db, pd.DataFrame([{"Username": "x"}]), by="owner"))

# time in and time out. 2026-10-05 00:30 UTC is 08:30 in Manila.
t0 = datetime(2026, 10, 5, 0, 30)
ok("status starts as out", a.status(db, "juan", t0)[0] == "out")
raises("time out without time in is refused", lambda: a.time_out(db, "juan", t0))
a.time_in(db, "juan", t0, TZ)
ok("after time in the status is in", a.status(db, "juan", t0 + timedelta(hours=1))[0] == "in")
raises("a second time in is refused while timed in", lambda: a.time_in(db, "juan", t0 + timedelta(minutes=5), TZ))
a.time_out(db, "juan", t0 + timedelta(hours=4))
a.time_in(db, "juan", t0 + timedelta(hours=5), TZ)
a.time_out(db, "juan", t0 + timedelta(hours=9, minutes=30))
r = a.records(db, "2026-10-05", "2026-10-05", "juan", TZ, at=t0 + timedelta(hours=10))
ok("two records in one day add up to 8.5 hours", len(r) == 2 and abs(r.hours.sum() - 8.5) < 1e-9 and set(r.status) == {"Complete"})
ok("times are shown in local time (08:30 Manila)", f"{r.in_local.min():%Y-%m-%d %H:%M}" == "2026-10-05 08:30")
# work date follows local time: 17:00 UTC on 4 Oct is 01:00 on 5 Oct in Manila
a.time_in(db, "maria", datetime(2026, 10, 4, 17, 0), TZ)
ok("the work date is the local date", a.records(db, "2026-10-05", "2026-10-05", "maria", TZ, at=t0).work_date.tolist() == ["2026-10-05"])
at = datetime(2026, 10, 5, 3, 0)
b = a.today_board(db, "2026-10-05", TZ, at=at).set_index("username")
ok("the day board shows In, Out and Not in", b.loc["maria", "status"] == "In" and b.loc["juan", "status"] == "Out" and b.loc["emp01", "status"] == "Not in" and len(b) == 69)
# forgotten time out
late = datetime(2026, 10, 6, 0, 30)
ok("an open record older than 16 hours is flagged", a.status(db, "maria", late)[0] == "no_time_out")
raises("time out on a flagged record is refused", lambda: a.time_out(db, "maria", late))
a.time_in(db, "maria", late, TZ)
ok("the person can still time in on the next day", a.status(db, "maria", late + timedelta(hours=1))[0] == "in")
a.time_out(db, "maria", late + timedelta(hours=8))
rep = a.report(db, "2026-10-01", "2026-10-31", TZ, at=late + timedelta(hours=9)).set_index("username")
ok("the report counts days, hours and records with no time out", rep.loc["juan", "days_present"] == 1 and abs(rep.loc["juan", "hours"] - 8.5) < 1e-9 and rep.loc["maria", "days_present"] == 2 and rep.loc["maria", "no_time_out"] == 1 and abs(rep.loc["maria", "hours"] - 8) < 1e-9 and rep.loc["emp01", "days_present"] == 0)
# corrections
bad = a.records(db, "2026-10-05", "2026-10-05", "maria", TZ, at=late).iloc[0]
raises("a correction needs a reason", lambda: a.correct_record(db, bad.id, datetime(2026, 10, 5, 1, 0), datetime(2026, 10, 5, 9, 0), "", "owner", TZ))
raises("a correction with time out before time in is refused", lambda: a.correct_record(db, bad.id, datetime(2026, 10, 5, 9, 0), datetime(2026, 10, 5, 1, 0), "x", "owner", TZ))
a.correct_record(db, bad.id, datetime(2026, 10, 5, 1, 0), datetime(2026, 10, 5, 9, 0), "Forgot to time out", "owner", TZ)
fixed = a.records(db, "2026-10-05", "2026-10-05", "maria", TZ, at=late).iloc[0]
ok("the owner's correction closes the record and keeps the reason", fixed.status == "Complete" and abs(fixed.hours - 8) < 1e-9 and fixed.note == "Forgot to time out" and fixed.edited_by == "owner")
a.add_record(db, "emp01", datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 17, 0), "Was on site, no device", "owner", TZ)
ok("the owner can add a missed record", abs(a.records(db, "2026-10-05", "2026-10-05", "emp01", TZ).hours.sum() - 9) < 1e-9)
raises("an added record needs a time out after the time in", lambda: a.add_record(db, "emp01", datetime(2026, 10, 5, 8, 0), datetime(2026, 10, 5, 8, 0), "x", "owner", TZ))
k.set_active(db, "emp02", False, "owner")
ok("a deactivated person leaves the day board and cannot sign in", "emp02" not in set(a.today_board(db, "2026-10-05", TZ, at=at).username) and k.check_login(db, "emp02", "whatever1") is None)
lg = k.recent_log(db, 400)
ok("time in, time out and corrections are in the activity log", {"time_in", "time_out", "correct_record", "add_record"} <= set(lg.action))
print(f"\n{sum(res)} of {len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
