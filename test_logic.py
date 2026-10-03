"""Checks the database, accounts and calculation layer.
Run: python test_logic.py
Uses a temporary SQLite file, or PostgreSQL when DATABASE_URL is set (use an empty test database)."""
import os, tempfile
import pandas as pd
os.environ.setdefault("KPI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
import kpi_logic as k

db = k.connect()
print("Backend:", "PostgreSQL" if db.is_pg else "SQLite")
has_owner = k.init_db(db, "owner", "Start1234")
df = k.load_fact(db); br = k.get_branches(db)

e = pd.read_csv("data/sample_entries.csv", parse_dates=["date"]); m = pd.read_csv("data/metrics.csv")
e = e.merge(m, on="metric"); e["adj"] = e["value"] * e["multiplier"]
res = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name); res.append(bool(cond))
def raises(name, fn):
    try: fn(); ok(name, False)
    except ValueError: ok(name, True)

ok("row count 56,700", len(df) == 56700 == len(e))
ok(f"total adjusted {df.adjusted.sum():,.1f} = 158,954.7", abs(df.adjusted.sum() - 158954.7) < 0.05 and abs(e.adj.sum() - df.adjusted.sum()) < 1e-6)
r = k.ranking(df, "2026-01-01", "2026-12-31", br)
ok(f"rank 1 = {r.iloc[0].branch} (Australia)", r.iloc[0].branch == "Australia")
ok("rank 15 = Russia", r[r["rank"] == 15].iloc[0].branch == "Russia")
ok("5 branches without data have no rank", r["rank"].isna().sum() == 5)
c, info = k.mtd_compare(df, "2026-09-30", br)
ok(f"Sep total {info['cur_total']:,.1f} = 18,383.3", abs(info["cur_total"] - 18383.3) < 0.05)
ok(f"Aug to same day {info['prev_total']:,.1f} = 15,692.6", abs(info["prev_total"] - 15692.6) < 0.05)
ok(f"MTD change {info['change_pct']:+.2%} = +17.15%", abs(info["change_pct"] - 0.1715) < 0.00005)
d = k.daily_breakdown(df, "2026-09-01", "2026-09-30")
ok("daily running total ends at Sep total", abs(d.running_total.iloc[-1] - 18383.3) < 0.05)
s = k.submission_check(db, "2026-09-28")
ok("submission 2026-09-28: 15 Submitted, 5 Not submitted", (s.status == "Submitted").sum() == 15 and (s.status == "Not submitted").sum() == 5)
q = k.data_quality(db); ok("data quality: 15 OK, 5 No data", (q.status == "OK").sum() == 15 and (q.status == "No data").sum() == 5)

# entries
k.save_day_entries(db, "Branch16", "2026-10-02", {"Cat_001": 3, "Cat_002": 0}, "t")
ok("partial entry shows Partial", k.submission_check(db, "2026-10-02").set_index("branch_code").loc["Branch16", "status"] == "Partial")
g = k.get_day_entries(db, "Branch16", "2026-10-02").set_index("metric")
ok("zero is kept as a real value, blank stays blank", g.loc["Cat_002", "value"] == 0 and pd.isna(g.loc["Cat_003", "value"]))
k.save_day_entries(db, "Branch16", "2026-10-02", {"Cat_001": 5}, "t")
ok("saving again updates the value", k.get_day_entries(db, "Branch16", "2026-10-02").set_index("metric").loc["Cat_001", "value"] == 5)
ok("data quality shows Partial days", k.data_quality(db).set_index("branch_code").loc["Branch16", "status"] == "Partial days")
sv, rm = k.save_day_entries(db, "Branch16", "2026-10-02", {"Cat_001": None, "Cat_002": None}, "t")
ok("clearing values removes the entries", rm == 2 and k.submission_check(db, "2026-10-02").set_index("branch_code").loc["Branch16", "status"] == "Not submitted")
raises("reject a negative value", lambda: k.save_day_entries(db, "Branch16", "2026-10-02", {"Cat_001": -1}, "t"))
raises("reject a decimal value", lambda: k.save_day_entries(db, "Branch16", "2026-10-02", {"Cat_001": 2.5}, "t"))
raises("a bad value saves nothing for that day", lambda: k.save_day_entries(db, "Branch16", "2026-10-02", {"Cat_001": 4, "Cat_002": -2}, "t"))
ok("nothing was saved after the bad value", k.submission_check(db, "2026-10-02").set_index("branch_code").loc["Branch16", "entered"] == 0)

# accounts
ok("first owner created from settings", has_owner and k.check_login(db, "owner", "Start1234")["role"] == "owner")
ok("no demo accounts exist", len(k.list_users(db)) == 1)
temp = k.new_temp_password()
k.create_user(db, "Branch01", "Ana Cruz", "branch", "Branch01", temp, by="owner")
u = k.check_login(db, "branch01", temp)
ok("new user signs in with the temporary password and must change it", u and u["must_change"] and u["branch_code"] == "Branch01")
ok("wrong password is refused", k.check_login(db, "branch01", "nope1234") is None)
ok("unknown user is refused", k.check_login(db, "nobody", "x") is None)
raises("duplicate username is refused", lambda: k.create_user(db, "branch01", "X", "branch", "Branch01", "Abcd1234", by="owner"))
raises("branch user needs a branch", lambda: k.create_user(db, "nobranch", "X", "branch", None, "Abcd1234", by="owner"))
raises("short password is refused", lambda: k.change_password(db, "branch01", temp, "ab1"))
raises("letters-only password is refused", lambda: k.change_password(db, "branch01", temp, "abcdefghij"))
raises("wrong current password is refused", lambda: k.change_password(db, "branch01", "wrong", "Newpass123"))
k.change_password(db, "branch01", temp, "Newpass123")
u = k.check_login(db, "branch01", "Newpass123")
ok("password change works and clears the temporary flag", u and not u["must_change"] and k.check_login(db, "branch01", temp) is None)
t2 = k.reset_password(db, "branch01", by="owner")
u = k.check_login(db, "branch01", t2)
ok("owner reset gives a new temporary password", u and u["must_change"] and k.check_login(db, "branch01", "Newpass123") is None)
k.set_active(db, "branch01", False, by="owner")
ok("deactivated user cannot sign in", k.check_login(db, "branch01", t2) is None)
raises("the last owner cannot be deactivated", lambda: k.set_active(db, "owner", False, by="owner"))
row = db.one("SELECT password_hash, salt FROM users WHERE username = ?", ("owner",))
ok("passwords are stored hashed with a per-user salt", "Start1234" not in row[0] and len(row[0]) == 64 and len(row[1]) == 32)
lg = k.recent_log(db, 200)
ok("activity log records sign-ins, failures and user changes", {"login", "login_failed", "create_user", "reset_password", "save_entries"} <= set(lg.action))
k.set_multiplier(db, "Cat_001", 0.9, "owner"); ok("multiplier change is saved", abs(k.get_metrics(db).set_index("metric").loc["Cat_001", "multiplier"] - 0.9) < 1e-9)
k.set_multiplier(db, "Cat_001", 0.7, "owner")
print(f"\n{sum(res)} of {len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
