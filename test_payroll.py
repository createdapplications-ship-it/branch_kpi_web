"""Checks the payroll calculation. Run: python test_payroll.py (SQLite, or PostgreSQL with DATABASE_URL)."""
import os, tempfile
from datetime import datetime
import pandas as pd
os.environ.setdefault("KPI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["SALARY_KEY"] = "test-key-only"
import kpi_logic as k
import att_logic as a
import hr_logic as h
import payroll_logic as p

db = k.connect()
print("Backend:", "PostgreSQL" if db.is_pg else "SQLite")
k.init_db(db, "owner", "Start1234", load_sample=False)
h.init_hr(db); p.init_payroll(db)
a.TZ_NAME = "Asia/Manila"
res = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name); res.append(bool(cond))
def raises(name, fn):
    try: fn(); ok(name, False)
    except ValueError: ok(name, True)
def near(x, y): return abs(x - y) < 0.011

S = p.pay_settings(db)
# contributions and tax tables
ok("SSS employee share: 26,100 rounds to a 26,000 credit, 5% = 1,300", p.sss_ee(26100, S) == 1300.0)
ok("SSS is capped at the 35,000 credit and floored at 5,000", p.sss_ee(80000, S) == 1750.0 and p.sss_ee(3000, S) == 250.0)
ok("PhilHealth employee share is 2.5% with a 10,000 floor and 100,000 ceiling", p.phic_ee(26100, S) == 652.5 and p.phic_ee(5000, S) == 250.0 and p.phic_ee(200000, S) == 2500.0)
ok("Pag-IBIG employee share is 2% of up to 10,000", p.hdmf_ee(26100, S) == 200.0 and p.hdmf_ee(1200, S) == 12.0)
ok("monthly tax: 20,833 and below is zero", p.withholding_tax(20000, "monthly") == 0)
ok("monthly tax: 30,000 = 15% of the excess over 20,833", near(p.withholding_tax(30000, "monthly"), (30000 - 20833) * 0.15))
ok("monthly tax: 50,000 = 1,875 + 20% of the excess over 33,333", near(p.withholding_tax(50000, "monthly"), 1875 + (50000 - 33333) * 0.20))
ok("semi-monthly tax: 20,000 = 937.50 + 20% over 16,667", near(p.withholding_tax(20000, "semi-monthly"), 937.5 + (20000 - 16667) * 0.2))

# set up two employees
for u in ("ana", "ben"):
    k.create_user(db, u, u.title(), "employee", "Branch01", "Abcd1234", by="owner", must_change=False)
h.save_employee(db, "hr", full_name="Ana Cruz", username="ana", branch_code="Branch01", civil_status="Married", rate_type="monthly", rate=26100)
h.save_employee(db, "hr", full_name="Ben Reyes", username="ben", branch_code="Branch01", civil_status="Single", rate_type="daily", rate=800)
rows, _ = h.read_schedule_table(db, pd.DataFrame([{"Employee": u, "Day": d, "Start": "08:00", "End": "17:00", "From": "2026-10-01", "To": "2026-10-15"}
                                                  for u in ("ana", "ben") for d in ("Mon", "Tue", "Wed", "Thu", "Fri")]
                                                 + [{"Employee": u, "Day": "Sat", "Rest Day": "Yes", "From": "2026-10-01", "To": "2026-10-15"} for u in ("ana", "ben")]))
h.import_schedules(db, rows, "hr")
def rec(u, d, i, o):
    a.add_record(db, u, datetime.fromisoformat(f"{d} {i}"), datetime.fromisoformat(f"{d} {o}"), "test", "owner")
work = [str(d.date()) for d in pd.bdate_range("2026-10-01", "2026-10-15")]   # 11 weekdays
for d in work:
    if d != "2026-10-07":
        rec("ana", d, "08:00", "17:00")
    rec("ben", d, "08:00", "17:00")
rec("ana", "2026-10-08", "08:00", "17:00")                     # same day twice is fine: hours add up
a.add_record(db, "ben", datetime(2026, 10, 10, 8), datetime(2026, 10, 10, 13), "rest day work", "owner")   # Saturday, a rest day
h.set_holiday(db, "2026-10-09", "Test regular holiday", "regular", "hr")
p.set_allowance(db, "ana", "RICE", 3000, "pay"); p.set_allowance(db, "ana", "TRANSPO", 2000, "pay")
raises("an unknown allowance is refused", lambda: p.set_allowance(db, "ana", "XYZ", 100, "pay"))

pid = p.create_period(db, "2026-10-01", "2026-10-15", "semi-monthly", "2026-10-15", part=1, by="pay")
raises("an overlapping period is refused", lambda: p.create_period(db, "2026-10-10", "2026-10-20", "semi-monthly", by="pay"))
lines, probs = p.compute_period(db, pid)
L = lines.set_index("username")
A = L.loc["ana"]
daily = 26100 * 12 / 261
ok("monthly rate: daily rate = rate x 12 / 261", near(A["daily_rate"], daily))
ok("monthly rate: one absence is deducted from half the monthly rate", A["absences"] == 1 and near(A["basic"], 13050 - daily))
ok("rice subsidy up to 1,250 per half month is tax free; transport is taxable", near(A["allowances"], 2500) and near(A["allowances_taxable"], 250 + 1000))
ok("contributions are split half each period", near(A["sss"], 650) and near(A["philhealth"], 326.25) and near(A["pagibig"], 100))
exp_tax = p.withholding_tax(A["basic"] + A["premiums"] + 1250 - (650 + 326.25 + 100), "semi-monthly")
ok("tax is on taxable pay after contributions", near(A["tax"], exp_tax) and near(A["net"], A["gross"] - A["contributions"] - A["tax"]))
B = L.loc["ben"]
ok("daily rate: paid for each ordinary day worked plus the regular holiday rate when worked", B["absences"] == 0 and near(B["basic"], 10 * 800))
ok("daily rate: worked regular holiday pays 200%, rest day 130%", near(B["holiday_pay"], 8 * 100 * 2) and near(B["rest_day_pay"], 5 * 100 * 1.30))
h.save_employee(db, "hr", emp_id=db.one("SELECT emp_id FROM employees WHERE username='ana'")[0], full_name="Ana Cruz", username="ana",
                branch_code="Branch01", civil_status="Single", rate_type="monthly")
ok("civil status does not change the tax (TRAIN law)", near(p.compute_period(db, pid)[0].set_index("username").loc["ana", "tax"], A["tax"]))

# adjustments and bonus
k.add_metric(db, "Closed deals", 1.0, "owner")
db.insert_many("entries", ["branch_code", "date", "metric", "value", "updated_at", "updated_by"],
               [["Branch01", "2026-09-%02d" % d, "Closed deals", 2.0, k.now(), "test"] for d in range(1, 31)])
p.set_target(db, "Branch01", "Closed deals", "2026-09", 50, "pay")
p.add_bonus_rule(db, "Closed deals", 100, "fixed", 1000, "pay")
p.add_bonus_rule(db, "Closed deals", 120, "pct_basic", 10, "pay")
ach = p.achievement(db, "2026-09").set_index("metric")
ok("achievement is actual over target", ach.loc["Closed deals", "actual"] == 60 and near(ach.loc["Closed deals", "pct"], 120))
pid2 = p.create_period(db, "2026-10-16", "2026-10-31", "semi-monthly", "2026-10-31", part=2, bonus_month="2026-09", by="pay")
p.add_adjustment(db, pid2, "ana", "Salary correction", 500, True, "pay")
p.add_adjustment(db, pid2, "ana", "Loan payment", -300, False, "pay")
L2 = p.compute_period(db, pid2)[0].set_index("username")
ok("the highest bonus tier reached applies (10% of basic at 120%)", near(L2.loc["ana", "bonus"], round(L2.loc["ana", "basic"] * 0.10, 2)))
ok("adjustments add to gross; only taxable ones are taxed", near(L2.loc["ana", "adjustments"], 200))
n = p.finalize_period(db, pid, "pay")
ok("finalizing stores one line per employee", n == 2 and len(p.final_lines(db, pid)) == 2)
raises("a final period cannot take adjustments", lambda: p.add_adjustment(db, pid, "ana", "x", 1, True, "pay"))
raises("a final period cannot be finalized again", lambda: p.finalize_period(db, pid, "pay"))
raw = db.one("SELECT data FROM pay_lines WHERE period_id = ? AND username = 'ana'", (pid,))[0]
ok("stored pay lines are encrypted", raw.startswith("enc:") and "13050" not in raw)
ok("the employee sees their final payslip", list(p.my_payslips(db, "ana")["id"]) == [pid])
tm = p.thirteenth_month(db, 2026).set_index("username")
ok("13th month = basic pay this year / 12", near(tm.loc["ana", "thirteenth_month"], round(A["basic"] / 12, 2)))
p.save_pay_settings(db, {"days_per_year": 313}, "pay")
ok("settings can be changed and are kept", p.pay_settings(db)["days_per_year"] == 313)
raises("an unknown setting is refused", lambda: p.save_pay_settings(db, {"foo": 1}, "pay"))
print(f"\n{sum(res)} of {len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
