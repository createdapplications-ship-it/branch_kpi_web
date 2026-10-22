"""Checks the CRM. Run: python test_crm.py (SQLite, or PostgreSQL with DATABASE_URL)."""
import os, tempfile
import pandas as pd
os.environ.setdefault("KPI_DB", os.path.join(tempfile.mkdtemp(), "test.db"))
import kpi_logic as k
import hr_logic as h
import payroll_logic as p
import crm_logic as c

db = k.connect()
print("Backend:", "PostgreSQL" if db.is_pg else "SQLite")
k.init_db(db, "owner", "Start1234", load_sample=False)
h.init_hr(db); p.init_payroll(db); c.init_crm(db)
res = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name); res.append(bool(cond))
def raises(name, fn):
    try: fn(); ok(name, False)
    except ValueError: ok(name, True)

for u, br in [("ana", "Branch01"), ("ben", "Branch01"), ("cara", "Branch02"), ("dan", "Branch02")]:
    k.create_user(db, u, u.title(), "employee", br, "Abcd1234", by="owner", must_change=False)

# clients
c1 = c.add_client(db, "ana", "Rosa Diaz", "Diaz Trading", "0917 123 4567", "rosa@diaz.ph", "Branch01", "Walk-in")
raises("a client needs a phone or email", lambda: c.add_client(db, "ana", "No Contact"))
raises("a duplicate phone is refused", lambda: c.add_client(db, "ben", "Rosa D.", phone="09171234567"))
raises("a bad email is refused", lambda: c.add_client(db, "ben", "X", email="not-an-email"))
up = pd.DataFrame([{"Name": f"Client {i:02d}", "Phone": f"0918000{i:04d}", "Branch": "Branch01" if i < 10 else "Branch02"} for i in range(20)]
                  + [{"Name": "Dup of Rosa", "Email": "ROSA@diaz.ph"}, {"Name": ""}])
n, skipped = c.bulk_clients(db, up, "owner")
ok("bulk upload adds new clients and skips duplicates", n == 20 and len(skipped) == 1)
ok("all new clients are untouched", len(c.untouched(db)) == 21)

# randomizer
counts = c.assign_random(db, ["ana", "ben"], "owner", branch_code="Branch01", seed=7)
ok("the randomizer shares a branch's untouched clients evenly", sorted(counts.values()) == [5, 6] and sum(counts.values()) == 11)
ok("assigned clients are no longer in the unassigned pool", len(c.untouched(db, "Branch01")) == 0 and len(c.untouched(db, "Branch01", include_assigned=True)) == 11)
counts2 = c.assign_random(db, ["cara", "dan"], "owner", seed=1)
ok("everyone assigned gets a notification", counts2 == {"cara": 5, "dan": 5} and len(c.my_notifications(db, "cara")) == 1)
raises("there is nothing left to assign", lambda: c.assign_random(db, ["ana"], "owner"))

# contacts and call-backs
raises("a call-back cannot be in the past", lambda: c.log_contact(db, c1, "ana", "Contacted", call_again_on="2020-01-01"))
w = c.log_contact(db, c1, "ana", "Contacted", "No answer", call_again_on=pd.Timestamp.today().date() + pd.Timedelta(days=2))
cl = c.clients(db).set_index("id").loc[c1]
ok("a contact sets the status, last contact and next call date", cl["status"] == "Call back" and cl["last_contact_by"] == "ana" and cl["next_call_on"] is not None and w == [])
ok("the call-back appears in the call list for the caller", len(c.call_list(db, "ana")) == 1)
w2 = c.log_contact(db, c1, "ben", "Interested", "Asked for a quote")
ok("a second person contacting the same client is warned, and the first is notified",
   len(w2) == 1 and "ana" in w2[0] and any("ben also contacted" in m for m in c.my_notifications(db, "ana")["message"]))
ok("ana's call-back is still pending (ben did not close it)", len(c.call_list(db, "ana")) == 1)
c.log_contact(db, c1, "ana", "Closed won", "Signed")
ok("closing the client cancels open call-backs", len(c.call_list(db, "ana")) == 0 and c.clients(db).set_index("id").loc[c1, "status"] == "Closed won")
raises("a closed client cannot get a call-back", lambda: c.log_contact(db, c1, "ana", "Closed won", call_again_on=pd.Timestamp.today().date()))
c2 = c.clients(db, assigned_to="ben").iloc[0]["id"]
c.log_contact(db, c2, "ben", "Call back", call_again_on=pd.Timestamp.today().date(), call_again_by="ana")
ok("a call-back can be given to someone else, who is told", len(c.call_list(db, "ana")) == 1 and any("asked you to call" in m for m in c.my_notifications(db, "ana")["message"]))
ok("due call-backs create one reminder per day", c.due_reminders(db, "ana") == 1 and c.due_reminders(db, "ana") == 0)
c.mark_read(db, "ana")
ok("notifications can be marked read", len(c.my_notifications(db, "ana")) == 0)

# KPI link
raises("only an existing metric can be linked", lambda: c.set_kpi_link(db, "Not a metric", "contacts", "validate", "owner"))
k.add_metric(db, "Client calls", 1.0, "owner")
c.set_kpi_link(db, "Client calls", "contacts", "validate", "owner")
today = str(pd.Timestamp.today().date())
cnt = c.crm_counts(db, today, today).set_index("branch_code")
ok("contacts are counted per branch per day", int(cnt.loc["Branch01", "crm_count"]) == 4)
k.save_day_entries(db, "Branch01", today, {"Client calls": 6}, "ana")
v = c.validation(db, today, today).set_index("branch_code")
ok("validation shows what the branch entered next to the CRM count", v.loc["Branch01", "check"] == "Higher than CRM" and v.loc["Branch01", "difference"] == 2)
ok("fill keeps entries a branch already typed", c.fill_kpi(db, today, today, "owner") == 0)
ok("fill with overwrite writes the CRM count", c.fill_kpi(db, today, today, "owner", overwrite=True) == 1 and
   float(db.one("SELECT value FROM entries WHERE branch_code='Branch01' AND metric='Client calls'")[0]) == 4)
p.set_target(db, "Branch01", "Client calls", today[:7], 8, "owner")
ba = c.branch_achievement(db, today[:7]).set_index("branch_code")
ok("branch achievement compares the CRM count with the target", ba.loc["Branch01", "pct"] == 50 and ba.loc["Branch01", "rank"] == 1)
print(f"\n{sum(res)} of {len(res)} checks passed"); raise SystemExit(0 if all(res) else 1)
