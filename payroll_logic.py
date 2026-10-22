"""Payroll calculation for the company portal.

No Streamlit code in this file, so it can be tested on its own.

What it does, per person per pay period:
  basic pay from the rate and the attendance (absences, late and undertime are deducted),
  premiums (approved overtime, night differential, rest day and holiday work),
  allowances (de minimis amounts up to their ceilings are not taxed),
  bonuses from Branch KPI actuals against targets, using rules set by management,
  manual adjustments, employee shares of SSS, PhilHealth and Pag-IBIG, and withholding tax.

Rates and tables are SETTINGS, not code. The defaults below follow the rules in force in 2026 as found in
public sources (see PAY_SOURCES). The payroll team must confirm every value before go-live, and update them
when the law changes. Civil status is kept on the employee record but does not change the tax: under the
TRAIN law the same graduated rates apply to everyone.

Not covered yet: minimum wage earner exemption, the 90,000 ceiling on 13th month and other benefits,
loans, and year-end tax annualization. Payroll staff handle these as adjustments until they are added.
"""
import json
import math
import re
import secrets
from datetime import date

import pandas as pd

import hr_logic as h
import kpi_logic as k

PAY_DEFAULTS = {
    "days_per_year": 261,          # monthly rate x 12 / this = daily rate (5-day week). Use 313 for a 6-day week.
    "hours_per_day": 8,
    "days_per_month_daily": 26,    # daily rate x this = monthly base for contributions
    "ot_rate": 1.25,               # overtime on an ordinary day
    "rest_day_rate": 1.30,         # work on a rest day
    "regular_holiday_premium": 1.00,   # extra on top of the day's pay when a regular holiday is worked
    "special_day_premium": 0.30,       # extra when a special non-working day is worked
    "night_diff": 0.10,            # extra per hour between 22:00 and 06:00
    "sss_rate_ee": 0.05, "sss_msc_min": 5000, "sss_msc_max": 35000,
    "phic_rate_ee": 0.025, "phic_floor": 10000, "phic_ceiling": 100000,
    "hdmf_rate_ee": 0.02, "hdmf_max_salary": 10000,
    "contrib_split": "split",      # semi-monthly: "split" half each period, or "second" all in the second period
}
PAY_SOURCES = [
    "Withholding tax: BIR RR 11-2018 Annex E, rates for 2023 onward (TRAIN law)",
    "De minimis ceilings: BIR RR 29-2025, effective 6 January 2026",
    "SSS 15% (employee 5%), salary credit 5,000 to 35,000; PhilHealth 5% (employee 2.5%), 10,000 to 100,000; "
    "Pag-IBIG 2%, fund salary up to 10,000",
    "Overtime, rest day, holiday and night differential: Labor Code rates",
]
# (lower bound, fixed tax, rate on the excess). Annex E, 2023 onward.
TAX_TABLES = {
    "monthly": [(0, 0, 0), (20833, 0, 0.15), (33333, 1875.00, 0.20), (66667, 8541.80, 0.25),
                (166667, 33541.80, 0.30), (666667, 183541.80, 0.35)],
    "semi-monthly": [(0, 0, 0), (10417, 0, 0.15), (16667, 937.50, 0.20), (33333, 4270.70, 0.25),
                     (83333, 16770.70, 0.30), (333333, 91770.70, 0.35)],
}
DEFAULT_ALLOWANCES = [
    # code, name, taxable, monthly tax-free ceiling (0 = fully taxable)
    ("RICE", "Rice subsidy", 0, 2500.00),
    ("UNIFORM", "Uniform and clothing allowance", 0, round(8000 / 12, 2)),
    ("LAUNDRY", "Laundry allowance", 0, 400.00),
    ("MEDDEP", "Medical cash allowance to dependents", 0, round(4000 / 12, 2)),
    ("TRANSPO", "Transportation allowance", 1, 0),
    ("COMM", "Communication allowance", 1, 0),
    ("MEAL", "Meal allowance", 1, 0),
]


def _schema(is_pg):
    num = "DOUBLE PRECISION" if is_pg else "REAL"
    return [
        f"""CREATE TABLE IF NOT EXISTS allowance_types (
            code TEXT PRIMARY KEY, name TEXT NOT NULL, taxable INTEGER NOT NULL DEFAULT 1,
            monthly_cap {num} NOT NULL DEFAULT 0)""",
        f"""CREATE TABLE IF NOT EXISTS employee_allowances (
            username TEXT NOT NULL, code TEXT NOT NULL, monthly_amount {num} NOT NULL,
            PRIMARY KEY (username, code))""",
        f"""CREATE TABLE IF NOT EXISTS kpi_targets (
            branch_code TEXT NOT NULL, metric TEXT NOT NULL, month TEXT NOT NULL, target {num} NOT NULL,
            PRIMARY KEY (branch_code, metric, month))""",
        f"""CREATE TABLE IF NOT EXISTS bonus_rules (
            id TEXT PRIMARY KEY, metric TEXT NOT NULL, min_pct {num} NOT NULL, kind TEXT NOT NULL,
            value {num} NOT NULL, active INTEGER NOT NULL DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS pay_periods (
            id TEXT PRIMARY KEY, start_date TEXT NOT NULL, end_date TEXT NOT NULL, pay_date TEXT,
            frequency TEXT NOT NULL, part INTEGER NOT NULL DEFAULT 1, bonus_month TEXT,
            status TEXT NOT NULL DEFAULT 'Draft', created_by TEXT, created_at TEXT, finalized_by TEXT, finalized_at TEXT)""",
        f"""CREATE TABLE IF NOT EXISTS pay_adjustments (
            id TEXT PRIMARY KEY, period_id TEXT NOT NULL, username TEXT NOT NULL, label TEXT NOT NULL,
            amount {num} NOT NULL, taxable INTEGER NOT NULL DEFAULT 1, created_by TEXT, created_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS pay_lines (
            period_id TEXT NOT NULL, username TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (period_id, username))""",
    ]


def init_payroll(db):
    db.run([(s, ()) for s in _schema(db.is_pg)])
    if db.one("SELECT COUNT(*) FROM allowance_types")[0] == 0:
        db.insert_many("allowance_types", ["code", "name", "taxable", "monthly_cap"], [list(x) for x in DEFAULT_ALLOWANCES])


# ---------------------------------------------------------------- settings
def pay_settings(db):
    s = dict(PAY_DEFAULTS)
    saved = h.get_setting(db, "pay_settings")
    if saved:
        s.update(json.loads(saved))
    return s


def save_pay_settings(db, values, by):
    s = pay_settings(db)
    for key, v in values.items():
        if key not in PAY_DEFAULTS:
            raise ValueError(f"Unknown setting {key}.")
        if key == "contrib_split":
            if v not in ("split", "second"):
                raise ValueError("Contribution timing must be split or second.")
            s[key] = v
        else:
            v = float(v)
            if v < 0:
                raise ValueError(f"{key} cannot be negative.")
            s[key] = v
    h.set_setting(db, "pay_settings", json.dumps(s), by)


# ---------------------------------------------------------------- contributions and tax
def sss_ee(base, s):
    msc = math.floor((base + 250) / 500) * 500
    msc = min(max(msc, s["sss_msc_min"]), s["sss_msc_max"])
    return round(msc * s["sss_rate_ee"], 2)


def phic_ee(base, s):
    return round(min(max(base, s["phic_floor"]), s["phic_ceiling"]) * s["phic_rate_ee"], 2)


def hdmf_ee(base, s):
    rate = 0.01 if base <= 1500 else s["hdmf_rate_ee"]
    return round(min(base, s["hdmf_max_salary"]) * rate, 2)


def withholding_tax(taxable, frequency):
    if taxable <= 0:
        return 0.0
    lower, fixed, rate = [row for row in TAX_TABLES[frequency] if taxable >= row[0]][-1]
    return round(fixed + (taxable - lower) * rate, 2)


# ---------------------------------------------------------------- allowances
def allowance_types(db):
    df = db.query("SELECT code, name, taxable, monthly_cap FROM allowance_types ORDER BY code")
    df["taxable"] = df["taxable"].astype(int)
    df["monthly_cap"] = df["monthly_cap"].astype(float)
    return df


def save_allowance_type(db, code, name, taxable, monthly_cap, by):
    code = (code or "").strip().upper()
    if not code or not (name or "").strip():
        raise ValueError("Enter a code and a name.")
    db.run([("DELETE FROM allowance_types WHERE code = ?", (code,)),
            ("INSERT INTO allowance_types (code, name, taxable, monthly_cap) VALUES (?,?,?,?)",
             (code, name.strip(), 1 if taxable else 0, float(monthly_cap or 0)))])
    k.log(db, by, "save_allowance_type", code)


def set_allowance(db, username, code, monthly_amount, by):
    if code not in set(allowance_types(db)["code"]):
        raise ValueError("Unknown allowance.")
    amt = float(monthly_amount)
    if amt < 0:
        raise ValueError("The amount cannot be negative.")
    db.run([("DELETE FROM employee_allowances WHERE username = ? AND code = ?", (username, code))] +
           ([("INSERT INTO employee_allowances (username, code, monthly_amount) VALUES (?,?,?)", (username, code, amt))] if amt else []))
    k.log(db, by, "set_allowance", f"{username} {code} {amt}")


def employee_allowances(db, username=None):
    sql = """SELECT e.username, e.code, t.name, t.taxable, t.monthly_cap, e.monthly_amount
             FROM employee_allowances e JOIN allowance_types t ON t.code = e.code"""
    df = db.query(sql + (" WHERE e.username = ?" if username else "") + " ORDER BY e.username, e.code",
                  (username,) if username else ())
    for c in ("monthly_cap", "monthly_amount"):
        df[c] = df[c].astype(float)
    df["taxable"] = df["taxable"].astype(int)
    return df


# ---------------------------------------------------------------- targets and bonuses
def set_target(db, branch_code, metric, month, target, by):
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must look like 2026-10.")
    db.run([("DELETE FROM kpi_targets WHERE branch_code = ? AND metric = ? AND month = ?", (branch_code, metric, month)),
            ("INSERT INTO kpi_targets (branch_code, metric, month, target) VALUES (?,?,?,?)",
             (branch_code, metric, month, float(target)))])
    k.log(db, by, "set_target", f"{branch_code} {metric} {month} {target}")


def get_targets(db, month=None):
    df = db.query("SELECT branch_code, metric, month, target FROM kpi_targets" + (" WHERE month = ?" if month else "") +
                  " ORDER BY month, branch_code, metric", (month,) if month else ())
    df["target"] = df["target"].astype(float)
    return df


def add_bonus_rule(db, metric, min_pct, kind, value, by):
    if kind not in ("fixed", "pct_basic"):
        raise ValueError("Bonus type must be a fixed amount or a percent of basic pay.")
    if float(min_pct) <= 0:
        raise ValueError("The achievement level must be above 0%.")
    rid = secrets.token_hex(6)
    db.run([("INSERT INTO bonus_rules (id, metric, min_pct, kind, value, active) VALUES (?,?,?,?,?,1)",
             (rid, metric, float(min_pct), kind, float(value)))])
    k.log(db, by, "add_bonus_rule", f"{metric} >= {min_pct}% {kind} {value}")
    return rid


def remove_bonus_rule(db, rid, by):
    db.run([("DELETE FROM bonus_rules WHERE id = ?", (rid,))])
    k.log(db, by, "remove_bonus_rule", rid)


def bonus_rules(db):
    df = db.query("SELECT id, metric, min_pct, kind, value FROM bonus_rules WHERE active = 1 ORDER BY metric, min_pct")
    for c in ("min_pct", "value"):
        df[c] = df[c].astype(float)
    return df


def achievement(db, month, fact=None):
    """Actual against target per branch and metric for a month. metric 'ALL' = total Adjusted Value;
    any other metric = the sum of its Metric Value."""
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Month must look like 2026-10.")
    t = get_targets(db, month)
    if t.empty:
        return t.assign(actual=pd.Series(dtype=float), pct=pd.Series(dtype=float))
    df = fact if fact is not None else k.load_fact(db)
    start = pd.Timestamp(month + "-01")
    end = start + pd.offsets.MonthEnd(0)
    d = df[(df["date"] >= start) & (df["date"] <= end)]
    allv = d.groupby("branch_code")["adjusted"].sum()
    byv = d.groupby(["branch_code", "metric"])["value"].sum()
    actual = [float(allv.get(b, 0.0)) if m == "ALL" else float(byv.get((b, m), 0.0)) for b, m in zip(t["branch_code"], t["metric"])]
    t["actual"] = actual
    t["pct"] = [a / tg * 100 if tg else None for a, tg in zip(t["actual"], t["target"])]
    return t


def bonus_for(db, username, month, basic, ach=None, branch_code=None):
    """Bonus lines for a person: for each metric with rules, the highest tier reached by their branch."""
    if branch_code is None:
        row = db.one("SELECT branch_code FROM employees WHERE username = ?", (username,)) or \
            db.one("SELECT branch_code FROM users WHERE username = ?", (username,))
        branch_code = row[0] if row else None
    if not branch_code or not month:
        return []
    rules = bonus_rules(db)
    ach = ach if ach is not None else achievement(db, month)
    mine = ach[ach["branch_code"] == branch_code].set_index("metric")
    out = []
    for metric, grp in rules.groupby("metric"):
        if metric not in mine.index or mine.loc[metric, "pct"] is None or pd.isna(mine.loc[metric, "pct"]):
            continue
        pct = float(mine.loc[metric, "pct"])
        hit = grp[grp["min_pct"] <= pct].sort_values("min_pct")
        if hit.empty:
            continue
        r = hit.iloc[-1]
        amount = r["value"] if r["kind"] == "fixed" else round(basic * r["value"] / 100, 2)
        label = "total Adjusted Value" if metric == "ALL" else metric
        out.append({"label": f"Bonus: {label} at {pct:.0f}% of target", "amount": round(float(amount), 2)})
    return out


# ---------------------------------------------------------------- pay periods
def create_period(db, start, end, frequency, pay_date=None, part=1, bonus_month=None, by="system"):
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    if end < start:
        raise ValueError("The end date must be after the start date.")
    if frequency not in TAX_TABLES:
        raise ValueError("Frequency must be monthly or semi-monthly.")
    clash = db.one("SELECT COUNT(*) FROM pay_periods WHERE start_date <= ? AND end_date >= ?", (str(end), str(start)))[0]
    if clash:
        raise ValueError("This period overlaps an existing pay period.")
    pid = secrets.token_hex(6)
    db.run([("""INSERT INTO pay_periods (id, start_date, end_date, pay_date, frequency, part, bonus_month, status, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,'Draft',?,?)""",
             (pid, str(start), str(end), str(pay_date) if pay_date else None, frequency, int(part), bonus_month or None, by, k.now()))])
    k.log(db, by, "create_pay_period", f"{start} to {end}")
    return pid


def periods(db):
    return db.query("""SELECT id, start_date, end_date, pay_date, frequency, part, bonus_month, status,
                              finalized_by, finalized_at FROM pay_periods ORDER BY start_date DESC""")


def get_period(db, pid):
    p = periods(db)
    p = p[p["id"] == pid]
    if p.empty:
        raise ValueError("Pay period not found.")
    row = p.iloc[0].copy()
    if not isinstance(row["bonus_month"], str) or not row["bonus_month"]:
        row["bonus_month"] = None
    return row


def add_adjustment(db, pid, username, label, amount, taxable, by):
    if get_period(db, pid)["status"] != "Draft":
        raise ValueError("This pay period is final. Add the adjustment to the next period.")
    if not (label or "").strip():
        raise ValueError("Enter a label, for example Loan payment or Salary correction.")
    aid = secrets.token_hex(6)
    db.run([("""INSERT INTO pay_adjustments (id, period_id, username, label, amount, taxable, created_by, created_at)
                VALUES (?,?,?,?,?,?,?,?)""", (aid, pid, username, label.strip(), float(amount), 1 if taxable else 0, by, k.now()))])
    k.log(db, by, "add_adjustment", f"{pid} {username} {label} {amount}")
    return aid


def adjustments(db, pid):
    df = db.query("SELECT id, username, label, amount, taxable FROM pay_adjustments WHERE period_id = ?", (pid,))
    df["amount"] = df["amount"].astype(float)
    df["taxable"] = df["taxable"].astype(int)
    return df


def compute_line(db, username, period, s=None, ds=None, ach=None):
    """Pay for one person in one period, as a dict of amounts. Raises ValueError when there is no rate."""
    s = s or pay_settings(db)
    rate_type, rate = h.employee_rate(db, username)
    if rate is None:
        raise ValueError(f"{username} has no rate on their employee record.")
    freq = period["frequency"]
    start, end = period["start_date"], period["end_date"]
    ds = ds if ds is not None else h.daily_status(db, start, end, [username])
    ds = ds[ds["username"] == username]
    hpd = float(s["hours_per_day"])
    if rate_type == "monthly":
        daily = rate * 12 / float(s["days_per_year"])
        base_month = rate
    else:
        daily = rate
        base_month = rate * float(s["days_per_month_daily"])
    hourly = daily / hpd
    late_min = float(ds["late_min"].sum()) + float(ds["undertime_min"].sum())
    late_ded = round(late_min / 60 * hourly, 2)
    unpaid_leave = float(ds.loc[(ds["leave_paid"] == 0), "leave_fraction"].sum()) if "leave_paid" in ds else 0.0
    paid_leave = float(ds.loc[(ds["leave_paid"] == 1), "leave_fraction"].sum()) if "leave_paid" in ds else 0.0
    absences = int((ds["status"] == "Absent").sum())
    worked = ds[ds["first_in"].notna()]
    reg_hol = worked[(worked["holiday"]) & (worked["holiday_kind"] == "regular")]
    spec_hol = worked[(worked["holiday"]) & (worked["holiday_kind"] == "special")]
    rest = worked[(worked["rest_day"]) & (~worked["holiday"])]
    if rate_type == "monthly":
        basic_period = rate / 2 if freq == "semi-monthly" else rate
        absence_ded = round((absences + unpaid_leave) * daily, 2)
        basic = max(round(basic_period - absence_ded - late_ded, 2), 0.0)
        holiday_pay = (reg_hol["worked_hours"].sum() * hourly * float(s["regular_holiday_premium"]) +
                       spec_hol["worked_hours"].sum() * hourly * float(s["special_day_premium"]))
    else:
        ordinary = worked[(~worked["holiday"]) & (~worked["rest_day"])]
        unworked_reg = ds[(ds["holiday"]) & (ds["holiday_kind"] == "regular") & (ds["first_in"].isna())]
        paid_days = len(ordinary) + paid_leave + len(unworked_reg)
        absence_ded = 0.0
        basic = max(round(paid_days * daily - late_ded, 2), 0.0)
        holiday_pay = (reg_hol["worked_hours"].sum() * hourly * (1 + float(s["regular_holiday_premium"])) +
                       spec_hol["worked_hours"].sum() * hourly * (1 + float(s["special_day_premium"])))
    ot_pay = float(ds["ot_hours"].sum()) * hourly * float(s["ot_rate"])
    nd_pay = float(ds["night_hours"].sum()) * hourly * float(s["night_diff"])
    rest_pay = float(rest["worked_hours"].sum()) * hourly * float(s["rest_day_rate"])
    premiums = round(ot_pay + nd_pay + rest_pay + holiday_pay, 2)

    share = 0.5 if freq == "semi-monthly" else 1.0
    allw = employee_allowances(db, username)
    allow_total = allow_taxable = 0.0
    allow_lines = []
    for _, r in allw.iterrows():
        amt = round(r["monthly_amount"] * share, 2)
        free = 0.0 if r["taxable"] else min(amt, round(r["monthly_cap"] * share, 2))
        allow_total += amt
        allow_taxable += amt - free
        allow_lines.append({"label": r["name"], "amount": amt, "tax_free": round(free, 2)})

    bonus_lines = bonus_for(db, username, period["bonus_month"], basic, ach) if period["bonus_month"] else []
    bonus = round(sum(b["amount"] for b in bonus_lines), 2)
    adj = adjustments(db, period["id"])
    adj = adj[adj["username"] == username]
    adj_total = round(float(adj["amount"].sum()), 2)
    adj_taxable = round(float(adj.loc[adj["taxable"] == 1, "amount"].sum()), 2)

    if freq == "semi-monthly":
        if s["contrib_split"] == "split":
            factor = 0.5
        else:
            factor = 1.0 if int(period["part"]) == 2 else 0.0
    else:
        factor = 1.0
    sss = round(sss_ee(base_month, s) * factor, 2)
    phic = round(phic_ee(base_month, s) * factor, 2)
    hdmf = round(hdmf_ee(base_month, s) * factor, 2)
    contributions = round(sss + phic + hdmf, 2)
    gross = round(basic + premiums + allow_total + bonus + adj_total, 2)
    taxable = round(max(basic + premiums + allow_taxable + bonus + adj_taxable - contributions, 0.0), 2)
    tax = withholding_tax(taxable, freq)
    net = round(gross - contributions - tax, 2)
    return {"username": username, "rate_type": rate_type, "rate": rate, "daily_rate": round(daily, 2),
            "hourly_rate": round(hourly, 2), "absences": absences, "unpaid_leave_days": unpaid_leave,
            "paid_leave_days": paid_leave, "late_undertime_min": round(late_min, 1),
            "absence_deduction": absence_ded, "late_deduction": late_ded, "basic": basic,
            "overtime_pay": round(ot_pay, 2), "night_diff_pay": round(nd_pay, 2), "rest_day_pay": round(rest_pay, 2),
            "holiday_pay": round(holiday_pay, 2), "premiums": premiums, "allowances": round(allow_total, 2),
            "allowances_taxable": round(allow_taxable, 2), "allowance_lines": allow_lines, "bonus": bonus,
            "bonus_lines": bonus_lines, "adjustments": adj_total,
            "adjustment_lines": adj[["label", "amount", "taxable"]].to_dict("records"),
            "gross": gross, "sss": sss, "philhealth": phic, "pagibig": hdmf, "contributions": contributions,
            "taxable": taxable, "tax": tax, "net": net}


def compute_period(db, pid):
    """Pay for every active employee with an account and a rate. Returns (lines table, problems)."""
    p = get_period(db, pid)
    if p["status"] == "Final":
        return final_lines(db, pid), pd.DataFrame(columns=["username", "problem"])
    emps = h.list_employees(db, active_only=True)
    emps = emps[emps["username"].notna()]
    users = list(emps["username"])
    s = pay_settings(db)
    ds = h.daily_status(db, p["start_date"], p["end_date"], users)
    ach = achievement(db, p["bonus_month"]) if p["bonus_month"] else None
    lines, problems = [], []
    for u in users:
        try:
            lines.append(compute_line(db, u, p, s, ds, ach))
        except ValueError as err:
            problems.append({"username": u, "problem": str(err)})
    df = pd.DataFrame(lines)
    if len(df):
        df = emps[["username", "emp_id", "full_name", "branch_code"]].merge(df, on="username", how="right")
    return df, pd.DataFrame(problems, columns=["username", "problem"])


def finalize_period(db, pid, by):
    p = get_period(db, pid)
    if p["status"] == "Final":
        raise ValueError("This pay period is already final.")
    lines, problems = compute_period(db, pid)
    if lines.empty:
        raise ValueError("There are no pay lines to finalize.")
    stmts = [("DELETE FROM pay_lines WHERE period_id = ?", (pid,))]
    for rec in lines.to_dict("records"):
        stmts.append(("INSERT INTO pay_lines (period_id, username, data) VALUES (?,?,?)",
                      (pid, rec["username"], h._enc(json.dumps(rec, default=str)))))
    stmts.append(("UPDATE pay_periods SET status = 'Final', finalized_by = ?, finalized_at = ? WHERE id = ?", (by, k.now(), pid)))
    db.run(stmts)
    k.log(db, by, "finalize_payroll", f"{p['start_date']} to {p['end_date']}: {len(lines)} lines, {len(problems)} skipped")
    return len(lines)


def final_lines(db, pid, username=None):
    rows = db.query("SELECT username, data FROM pay_lines WHERE period_id = ?" + (" AND username = ?" if username else ""),
                    (pid, username) if username else (pid,))
    return pd.DataFrame([json.loads(h._dec(d)) for d in rows["data"]])


def my_payslips(db, username):
    """Final pay periods that have a line for this person, newest first."""
    p = db.query("""SELECT p.id, p.start_date, p.end_date, p.pay_date FROM pay_periods p
                    JOIN pay_lines l ON l.period_id = p.id
                    WHERE p.status = 'Final' AND l.username = ? ORDER BY p.start_date DESC""", (username,))
    return p


def thirteenth_month(db, year):
    """Basic pay in final periods of the year divided by 12, per person."""
    p = db.query("SELECT id FROM pay_periods WHERE status = 'Final' AND end_date >= ? AND end_date <= ?",
                 (f"{year}-01-01", f"{year}-12-31"))
    frames = [final_lines(db, pid) for pid in p["id"]]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame(columns=["username", "full_name", "basic_year", "thirteenth_month"])
    allf = pd.concat(frames)
    g = allf.groupby(["username", "full_name"], as_index=False)["basic"].sum().rename(columns={"basic": "basic_year"})
    g["thirteenth_month"] = (g["basic_year"] / 12).round(2)
    return g
