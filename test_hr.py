"""Checks employees, schedules, attendance requests, leave and the daily status.
Run: python test_hr.py   (SQLite by default; PostgreSQL when DATABASE_URL is set, use an empty test database)."""
import os, tempfile
from datetime import datetime, date
import pandas as pd
os.environ.setdefault("KPI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["SALARY_KEY"] = "test-key-only"
import kpi_logic as k
import att_logic as a
import hr_logic as h

db = k.connect()
print("Backend:", "PostgreSQL" if db.is_pg else "SQLite")
k.init_db(db, "owner", "Start1234", load_sample=False)
h.init_hr(db)
res = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name); res.append(bool(cond))
def raises(name, fn):
    try: fn(); ok(name, False)
    except ValueError: ok(name, True)

TZ = "Asia/Manila"; a.TZ_NAME = TZ
for u, role, br in [("ana", "employee", "Branch01"), ("ben", "employee", "Branch01"), ("sup1", "supervisor", "Branch01"),
                    ("sup6", "supervisor", "Branch06"), ("hr1", "hr", None), ("pay1", "payroll", None)]:
    k.create_user(db, u, u.title(), role, br, "Abcd1234", by="owner", must_change=False)
raises("a supervisor needs a branch", lambda: k.create_user(db, "supx", "X", "supervisor", None, "Abcd1234", by="owner"))
OWNER = {"username": "owner", "role": "owner", "branch_code": None}
SUP1 = {"username": "sup1", "role": "supervisor", "branch_code": "Branch01"}
SUP6 = {"username": "sup6", "role": "supervisor", "branch_code": "Branch06"}

# employees
e1 = h.save_employee(db, "hr1", full_name="Ana Cruz", username="ana", branch_code="Branch01", position="Encoder",
                     employment_status="Regular", civil_status="Married", date_hired="2024-03-01", rate_type="monthly", rate=26100)
e2 = h.save_employee(db, "hr1", full_name="Ben Reyes", username="ben", branch_code="Branch01", rate_type="daily", rate=800)
ok("employee IDs are given in order by year", e1 == f"{date.today().year}-0001" and e2 == f"{date.today().year}-0002")
raw = db.one("SELECT rate_enc FROM employees WHERE emp_id = ?", (e1,))[0]
ok("salary is stored encrypted and reads back", raw.startswith("enc:") and "26100" not in raw and h.employee_rate(db, "ana") == ("monthly", 26100.0))
ok("the list without pay hides the rate", "rate" not in h.list_employees(db).columns and h.list_employees(db, with_pay=True).set_index("emp_id").loc[e1, "rate"] == 26100)
raises("one account cannot link to two employees", lambda: h.save_employee(db, "hr1", full_name="X", username="ana"))
h.save_employee(db, "hr1", emp_id=e1, full_name="Ana Cruz", username="ana", branch_code="Branch01", rate_type="monthly", bank="BDO 1234")
ok("bank details are not stored while the setting is off", db.one("SELECT bank_enc FROM employees WHERE emp_id = ?", (e1,))[0] is None)
h.set_setting(db, "store_bank_details", "1", "owner")
h.save_employee(db, "hr1", emp_id=e1, full_name="Ana Cruz", username="ana", branch_code="Branch01", rate_type="monthly", bank="BDO 1234")
ok("bank details are stored encrypted when the setting is on", h.list_employees(db, with_pay=True).set_index("emp_id").loc[e1, "bank"] == "BDO 1234")
ok("clearing bank details removes them all", h.clear_bank_details(db, "owner") == 1)
h.set_setting(db, "store_bank_details", "0", "owner")
ok("an update without a rate keeps the stored rate", h.employee_rate(db, "ana") == ("monthly", 26100.0))
done, probs = h.bulk_employees(db, pd.DataFrame([{"Full Name": "Cara Lim", "Branch": "Branch02", "Rate": "18,000"},
                                                 {"Full Name": "", "Branch": "Branch02"},
                                                 {"Full Name": "Bad Branch", "Branch": "Branch99"}]), "hr1")
ok("bulk upload adds employees and reports problems; rate skipped without pay access",
   len(done) == 1 and len(probs) == 1 and h.list_employees(db, with_pay=True).set_index("full_name").loc["Cara Lim", "rate"] is None)

# schedules: weekly pattern for October 2026 (Mon-Fri 08:00-17:00, Sat rest)
weekly = pd.DataFrame([{"Employee": e, "Day": d, "Start": "08:00", "End": "17:00", "Break Minutes": 60,
                        "Rest Day": "No", "From": "2026-10-01", "To": "2026-10-31"} for e in (e1, "ben") for d in ("Mon", "Tue", "Wed", "Thu", "Fri")]
                      + [{"Employee": e, "Day": "Sat", "Rest Day": "Yes", "From": "2026-10-01", "To": "2026-10-31"} for e in (e1, "ben")])
rows, probs = h.read_schedule_table(db, weekly)
ok("a weekly pattern turns into one row per day", len(rows) == 2 * (22 + 5) and probs.empty)
h.import_schedules(db, rows, "hr1")
rows2, probs2 = h.read_schedule_table(db, pd.DataFrame([{"Employee": "ana", "Date": "2026-10-10", "Start": "09:00", "End": "13:00"},
                                                        {"Employee": "nobody", "Date": "2026-10-10", "Start": "09:00", "End": "13:00"},
                                                        {"Employee": "ana", "Date": "2026-10-12", "Start": "8am", "End": "5pm"}]))
ok("a by-date upload replaces one day and reports bad rows", len(rows2) == 1 and len(probs2) == 2)
h.import_schedules(db, rows2, "hr1")
ok("the replaced day is now a working day", h.get_schedules(db, "2026-10-10", "2026-10-10", ["ana"]).iloc[0]["shift_start"] == "09:00")

# attendance: 08:10-17:00 on 5 Oct (late), 07:55-16:00 on 6 Oct (undertime), nothing on 7 Oct (absent)
def rec(u, d, i, o):
    a.add_record(db, u, datetime.fromisoformat(f"{d} {i}"), datetime.fromisoformat(f"{d} {o}"), "test", "owner", TZ)
rec("ana", "2026-10-05", "08:10", "17:00"); rec("ana", "2026-10-06", "07:55", "16:00"); rec("ana", "2026-10-08", "08:00", "20:00")
h.set_holiday(db, "2026-10-09", "Test holiday", "special", "hr1")
rec("ana", "2026-10-09", "08:00", "17:00")
ds = h.daily_status(db, "2026-10-05", "2026-10-10", ["ana"], today="2026-10-20").set_index("work_date")
ok("late, undertime, absent, holiday worked and rest day are worked out from the schedule",
   ds.loc["2026-10-05", "status"] == "Late" and ds.loc["2026-10-05", "late_min"] == 10 and
   ds.loc["2026-10-06", "status"] == "Undertime" and ds.loc["2026-10-06", "undertime_min"] == 60 and
   ds.loc["2026-10-07", "status"] == "Absent" and ds.loc["2026-10-09", "status"] == "Holiday worked")
ok("worked hours take off the break", abs(ds.loc["2026-10-05", "worked_hours"] - (8 + 50 / 60 - 1)) < 1e-9)

# requests
raises("a correction needs a reason", lambda: h.request_attendance(db, "ana", "2026-10-07", "Missing time in or out", "", "08:00", "17:00"))
r1 = h.request_attendance(db, "ana", "2026-10-07", "Missing time in or out", "Phone died", "08:00", "17:00")
r2 = h.request_attendance(db, "ana", "2026-10-08", "Overtime", "Month-end", ot_hours=3)
raises("a supervisor of another branch cannot approve", lambda: h.review_att_request(db, r1, True, SUP6))
ok("a supervisor sees only their branch's requests", len(h.list_att_requests(db, status="Pending", approver=SUP6)) == 0 and len(h.list_att_requests(db, status="Pending", approver=SUP1)) == 2)
h.review_att_request(db, r1, True, SUP1, "ok"); h.review_att_request(db, r2, True, SUP1)
raises("a request cannot be approved twice", lambda: h.review_att_request(db, r1, True, SUP1))
ds = h.daily_status(db, "2026-10-07", "2026-10-08", ["ana"], today="2026-10-20").set_index("work_date")
ok("an approved correction adds the record, and approved overtime is counted",
   ds.loc["2026-10-07", "status"] == "Present" and ds.loc["2026-10-08", "ot_hours"] == 3)
r3 = h.request_attendance(db, "ana", "2026-10-05", "Wrong time", "Was on time", "08:00", None)
h.review_att_request(db, r3, True, OWNER)
ok("an approved time-in change fixes the late mark", h.daily_status(db, "2026-10-05", "2026-10-05", ["ana"], today="2026-10-20").iloc[0]["late_min"] == 0)

# leave
ok("Service Incentive Leave starts at 5 days", h.leave_balances(db, "ana", 2026).set_index("code").loc["SIL", "remaining"] == 5)
l1 = h.request_leave(db, "ana", "SIL", "2026-10-12", "2026-10-14", "Family")
ok("leave counts working days only", h.list_leave_requests(db, "ana").iloc[0]["days"] == 3)
raises("overlapping leave is refused", lambda: h.request_leave(db, "ana", "VL", "2026-10-13", "2026-10-13"))
raises("leave beyond the balance is refused", lambda: h.request_leave(db, "ana", "SIL", "2026-10-19", "2026-10-23"))
h.review_leave(db, l1, True, SUP1)
ok("approved leave reduces the balance", h.leave_balances(db, "ana", 2026).set_index("code").loc["SIL", "remaining"] == 2)
ok("approved leave shows in the daily status", h.daily_status(db, "2026-10-13", "2026-10-13", ["ana"], today="2026-10-20").iloc[0]["status"] == "On leave")
l2 = h.request_leave(db, "ana", "LWOP", "2026-10-15", "2026-10-15", half_day=True)
h.cancel_request(db, "leave_requests", l2, "ana")
raises("a cancelled request cannot be cancelled again", lambda: h.cancel_request(db, "leave_requests", l2, "ana"))
h.set_leave_balance(db, "ana", 2026, "VL", 10, "hr1")
ok("HR can set an opening balance", h.leave_balances(db, "ana", 2026).set_index("code").loc["VL", "entitled"] == 10)

# night hours and summary
ok("night hours count 22:00 to 06:00", abs(h._night_hours(datetime(2026, 10, 1, 20), datetime(2026, 10, 2, 7)) - 8) < 1e-9)
sm = h.attendance_summary(db, "2026-10-01", "2026-10-31", ["ana"], today="2026-10-20").iloc[0]
ok("the summary counts days, absences, leave and overtime", sm["days_present"] == 5 and sm["leave_days"] == 3 and sm["ot_hours"] == 3 and sm["absences"] >= 1)
print(f"\n{sum(res)} of {len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
