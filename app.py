"""Branch KPI web app.

Run on a PC:   streamlit run app.py        (uses a local SQLite file)
Run hosted:    set DATABASE_URL, ADMIN_USERNAME and ADMIN_PASSWORD as secrets (uses PostgreSQL)
"""
import os
from datetime import date

import pandas as pd
import streamlit as st

import kpi_logic as k

st.set_page_config(page_title="Branch KPI", layout="wide")


def cfg(name, default=None):
    """Read a setting from Streamlit secrets first, then from the environment."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


@st.cache_resource
def get_db():
    db = k.connect(cfg("DATABASE_URL", ""))
    has_owner = k.init_db(db, cfg("ADMIN_USERNAME"), cfg("ADMIN_PASSWORD"),
                          load_sample=str(cfg("LOAD_SAMPLE_DATA", "true")).lower() in ("1", "true", "yes"))
    return db, has_owner


db, HAS_OWNER = get_db()

PAGES = {
    "branch": ["Daily Entry", "My Branch", "My Account"],
    "manager": ["Main Dashboard", "KPI Dashboard", "Drill-down", "My Account"],
    "owner": ["Main Dashboard", "KPI Dashboard", "Drill-down", "Submission Check",
              "Data Quality", "Daily Entry", "Users", "Admin", "My Account"],
}


def fmt_table(df, cols, formats=None):
    t = df[list(cols)].rename(columns=cols)
    st.dataframe(t.style.format(formats or {}, na_rep=""), use_container_width=True, hide_index=True)


def branch_label(branches):
    names = branches.set_index("branch_code")["branch"]
    return lambda c: f"{c} - {names[c]}"


# ---------------------------------------------------------------- sign-in
def setup_page():
    """Shown only when no owner account exists yet."""
    st.title("Branch KPI: first-time setup")
    if db.is_pg:
        st.error("No owner account exists. Set ADMIN_USERNAME and ADMIN_PASSWORD in the app secrets, "
                 "then restart the app.")
        return
    st.caption("Create the owner account. The owner adds all other users.")
    with st.form("setup"):
        username = st.text_input("Owner username")
        full_name = st.text_input("Full name")
        p1 = st.text_input("Password", type="password")
        p2 = st.text_input("Repeat password", type="password")
        ok = st.form_submit_button("Create owner")
    if ok:
        try:
            if p1 != p2:
                raise ValueError("The two passwords do not match.")
            k.create_user(db, username, full_name, "owner", None, p1, by="setup", must_change=False)
            get_db.clear()
            st.rerun()
        except ValueError as err:
            st.error(str(err))


def login_page():
    st.title("Branch KPI")
    st.caption("Sign in to enter daily values or view the dashboard.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        user = k.check_login(db, username, password)
        if user:
            st.session_state["user"] = user
            token = k.create_session(db, user["username"])
            st.session_state["token"] = token
            st.query_params["s"] = token      # keeps the sign-in after a page refresh
            st.rerun()
        else:
            st.error("Wrong username or password, or the account is not active.")
    st.caption("No account? Ask the dashboard owner to create one.")


def password_form(user, forced):
    if forced:
        st.title("Set a new password")
        st.info("You signed in with a temporary password. Choose your own password to continue.")
    with st.form("change_password"):
        old = st.text_input("Current password", type="password")
        new1 = st.text_input(f"New password (at least {k.MIN_PASSWORD} characters, letters and numbers)", type="password")
        new2 = st.text_input("Repeat new password", type="password")
        ok = st.form_submit_button("Change password")
    if ok:
        try:
            if new1 != new2:
                raise ValueError("The two new passwords do not match.")
            k.change_password(db, user["username"], old, new1)
            user["must_change"] = False
            st.session_state["user"] = user
            st.success("Password changed.")
            if forced:
                st.rerun()
        except ValueError as err:
            st.error(str(err))


# ---------------------------------------------------------------- pages
def page_daily_entry(user):
    st.title("Daily Entry")
    branches = k.get_branches(db)
    if user["role"] == "branch":
        code = user["branch_code"]
    else:
        code = st.selectbox("Branch", branches["branch_code"], format_func=branch_label(branches))
    name = branches.set_index("branch_code").loc[code, "branch"]
    day = st.date_input("Date", value=k.last_working_day(), max_value=date.today())
    st.subheader(f"{code} - {name}, {day:%a %d %b %Y}")
    if day.weekday() >= 5:
        st.warning("This date is a weekend.")
    current = k.get_day_entries(db, code, day)
    st.caption("Type a whole number of 0 or higher. Leave a cell blank if there is nothing to report. "
               "Enter 0 only when the result was zero.")
    edited = st.data_editor(
        current.rename(columns={"metric": "Metric", "multiplier": "Multiplier", "value": "Metric Value"}),
        disabled=["Metric", "Multiplier"], hide_index=True, use_container_width=True,
        column_config={"Metric Value": st.column_config.NumberColumn(min_value=0, step=1, format="%d")},
        key=f"editor_{code}_{day}")
    filled = int(edited["Metric Value"].notna().sum())
    st.write(f"{filled} of {len(edited)} metrics entered.")
    if st.button("Save", type="primary"):
        try:
            values = dict(zip(edited["Metric"], edited["Metric Value"]))
            saved, removed = k.save_day_entries(db, code, day, values, user["username"])
            st.success(f"Saved {saved} values for {day:%d %b %Y}." + (f" Removed {removed}." if removed else ""))
        except ValueError as err:
            st.error(str(err))


def page_my_branch(user):
    st.title("My Branch")
    df = k.load_fact(db)
    code = user["branch_code"]
    mine = df[df["branch_code"] == code]
    as_of = k.latest_data_date(mine) if len(mine) else date.today()
    start, _ = k.month_bounds(as_of)
    d = k.daily_breakdown(df, start, as_of, code)
    c1, c2 = st.columns(2)
    c1.metric("Adjusted Value, month to date", f"{d['adjusted'].sum():,.1f}")
    c2.metric("Days reported this month", f"{len(d)}")
    if len(d):
        st.bar_chart(d.set_index("date")["adjusted"])
    st.subheader("By metric, month to date")
    fmt_table(k.metric_breakdown(df, start, as_of, code),
              {"metric": "Metric", "multiplier": "Multiplier", "metric_value": "Metric Value",
               "adjusted": "Adjusted Value", "share": "Share"},
              {"Multiplier": "{:.1f}", "Metric Value": "{:,.0f}", "Adjusted Value": "{:,.1f}", "Share": "{:.1%}"})


def page_main_dashboard(user):
    st.title("Main Dashboard")
    df = k.load_fact(db)
    branches = k.get_branches(db)
    as_of = st.date_input("As of date", value=k.latest_data_date(df), max_value=date.today())
    table, info = k.mtd_compare(df, as_of, branches)
    st.caption(f"Month to date {info['cur_start']:%d %b} to {info['cur_end']:%d %b %Y}, compared with "
               f"{info['prev_start']:%d %b} to {info['prev_end']:%d %b %Y}.")
    top = table.dropna(subset=["rank"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Adjusted Value, MTD", f"{info['cur_total']:,.1f}",
              f"{info['change_pct']:+.1%} vs previous month" if info["change_pct"] is not None else None)
    c2.metric("Previous month, same days", f"{info['prev_total']:,.1f}")
    c3.metric("Top branch", top.iloc[0]["branch"] if len(top) else "No data")
    c4.metric("Branches reporting", f"{len(top)} of {len(branches)}")
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Ranking, month to date")
        fmt_table(table,
                  {"rank": "Rank", "branch": "Branch", "adjusted": "Adjusted Value", "prev_adjusted": "Previous Month",
                   "change_pct": "Change %", "prev_rank": "Previous Rank", "rank_change": "Rank Change",
                   "days_reported": "Days Reported"},
                  {"Rank": "{:.0f}", "Adjusted Value": "{:,.1f}", "Previous Month": "{:,.1f}", "Change %": "{:+.1%}",
                   "Previous Rank": "{:.0f}", "Rank Change": "{:+.0f}", "Days Reported": "{:.0f}"})
    with right:
        st.subheader("Daily Adjusted Value")
        d = k.daily_breakdown(df, info["cur_start"], info["cur_end"])
        if len(d):
            st.bar_chart(d.set_index("date")["adjusted"])
            st.subheader("Running total")
            st.line_chart(d.set_index("date")["running_total"])
        else:
            st.info("No entries yet for this month.")


def page_kpi_dashboard(user):
    st.title("KPI Dashboard")
    df = k.load_fact(db)
    branches = k.get_branches(db)
    latest = k.latest_data_date(df)
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("From", value=latest.replace(day=1))
    end = c2.date_input("To", value=latest)
    metric = c3.selectbox("Metric", ["All metrics"] + list(k.get_metrics(db)["metric"]))
    if start > end:
        st.error("From must be on or before To.")
        return
    d = df if metric == "All metrics" else df[df["metric"] == metric]
    r = k.ranking(d, start, end, branches)
    have = r.dropna(subset=["rank"])
    m1, m2, m3 = st.columns(3)
    m1.metric("Adjusted Value", f"{have['adjusted'].sum():,.1f}")
    m2.metric("Top branch", have.iloc[0]["branch"] if len(have) else "No data")
    m3.metric("Lowest branch", have.iloc[-1]["branch"] if len(have) else "No data")
    left, right = st.columns([3, 2])
    with left:
        fmt_table(r, {"rank": "Rank", "branch": "Branch", "adjusted": "Adjusted Value", "share": "Share of Company",
                      "days_reported": "Days Reported", "avg_per_day": "Avg per Day", "last_date": "Last Reported"},
                  {"Rank": "{:.0f}", "Adjusted Value": "{:,.1f}", "Share of Company": "{:.1%}",
                   "Days Reported": "{:.0f}", "Avg per Day": "{:,.1f}", "Last Reported": "{:%d %b %Y}"})
    with right:
        if len(have):
            st.bar_chart(have.set_index("branch")["adjusted"])
    st.download_button("Download ranking as CSV", r.to_csv(index=False), "ranking.csv", "text/csv")


def page_drill_down(user):
    st.title("Drill-down")
    df = k.load_fact(db)
    branches = k.get_branches(db)
    latest = k.latest_data_date(df)
    c1, c2, c3 = st.columns(3)
    code = c1.selectbox("Branch", branches["branch_code"], format_func=branch_label(branches))
    start = c2.date_input("From", value=latest.replace(day=1), key="dd_from")
    end = c3.date_input("To", value=latest, key="dd_to")
    d = k.daily_breakdown(df, start, end, code)
    if not len(d):
        st.info("No entries for this branch in the selected dates.")
        return
    st.metric("Adjusted Value", f"{d['adjusted'].sum():,.1f}")
    left, right = st.columns(2)
    with left:
        st.subheader("By day")
        st.bar_chart(d.set_index("date")["adjusted"])
    with right:
        st.subheader("By metric")
        fmt_table(k.metric_breakdown(df, start, end, code),
                  {"metric": "Metric", "multiplier": "Multiplier", "metric_value": "Metric Value",
                   "adjusted": "Adjusted Value", "share": "Share"},
                  {"Multiplier": "{:.1f}", "Metric Value": "{:,.0f}", "Adjusted Value": "{:,.1f}", "Share": "{:.1%}"})


def page_submission_check(user):
    st.title("Submission Check")
    day = st.date_input("Check date", value=k.last_working_day(), max_value=date.today())
    s = k.submission_check(db, day)
    c1, c2, c3 = st.columns(3)
    c1.metric("Submitted", int((s["status"] == "Submitted").sum()))
    c2.metric("Partial", int((s["status"] == "Partial").sum()))
    c3.metric("Not submitted", int((s["status"] == "Not submitted").sum()))
    fmt_table(s.sort_values(["status", "branch_code"]),
              {"branch_code": "Branch Code", "branch": "Branch", "entered": "Metrics Entered",
               "expected": "Expected", "status": "Status"})
    st.caption("A branch on holiday shows Not submitted. Confirm holidays before following up.")


def page_data_quality(user):
    st.title("Data Quality")
    fmt_table(k.data_quality(db),
              {"branch_code": "Branch Code", "branch": "Branch", "first_date": "First Date", "last_date": "Last Date",
               "days_reported": "Days Reported", "partial_days": "Partial Days", "status": "Status"})
    st.caption("OK: up to date and complete. Behind: last date is older than other branches. "
               "Partial days: some days have fewer than all metrics. No data: no entries yet.")


def page_users(user):
    st.title("Users")
    branches = k.get_branches(db)
    users = k.list_users(db)
    show = users.assign(must_change=users["must_change"].astype(int).map({1: "Yes", 0: "No"}),
                        active=users["active"].astype(int).map({1: "Yes", 0: "No"}))
    fmt_table(show, {"username": "Username", "full_name": "Full Name", "role": "Role", "branch_code": "Branch",
                     "must_change": "Temporary Password", "active": "Active", "created_at": "Created"})

    st.subheader("Add a user")
    with st.form("add_user"):
        c1, c2 = st.columns(2)
        username = c1.text_input("Username (for example branch01 or a name)")
        full_name = c2.text_input("Full name")
        role = c1.selectbox("Role", list(k.ROLES))
        code = c2.selectbox("Branch (for the branch role only)", branches["branch_code"], format_func=branch_label(branches))
        add = st.form_submit_button("Create user")
    if add:
        try:
            temp = k.new_temp_password()
            name = k.create_user(db, username, full_name, role, code if role == "branch" else None, temp,
                                 by=user["username"])
            st.success(f"User {name} created. Temporary password: {temp}")
            st.caption("Give this password to the user. It is shown only once. They must change it at first sign-in.")
        except ValueError as err:
            st.error(str(err))

    st.subheader("Reset password or change access")
    with st.form("manage_user"):
        target = st.selectbox("User", list(users["username"]))
        action = st.radio("Action", ["Reset password", "Deactivate", "Activate"])
        go = st.form_submit_button("Apply")
    if go:
        try:
            if action == "Reset password":
                temp = k.reset_password(db, target, by=user["username"])
                st.success(f"Temporary password for {target}: {temp}")
                st.caption("It is shown only once. The user must change it at next sign-in.")
            else:
                if target == user["username"] and action == "Deactivate":
                    raise ValueError("You cannot deactivate your own account.")
                k.set_active(db, target, action == "Activate", by=user["username"])
                st.success(f"{target}: {action.lower()}d.")
        except ValueError as err:
            st.error(str(err))


def page_admin(user):
    st.title("Admin")
    st.caption("Database: " + ("PostgreSQL" if db.is_pg else "local SQLite file"))
    st.subheader("Multipliers")
    st.warning("Changing a multiplier changes every past Adjusted Value. Export a copy of the data first.")
    m = k.get_metrics(db)
    edited = st.data_editor(m.rename(columns={"metric": "Metric", "multiplier": "Multiplier"}),
                            disabled=["Metric"], hide_index=True, key="mult_editor")
    if st.button("Save multipliers"):
        changed = 0
        for (_, old), (_, new) in zip(m.iterrows(), edited.iterrows()):
            if pd.notna(new["Multiplier"]) and float(new["Multiplier"]) != float(old["multiplier"]):
                k.set_multiplier(db, old["metric"], new["Multiplier"], user["username"])
                changed += 1
        st.success(f"{changed} multiplier(s) updated.")
    st.subheader("Branches")
    fmt_table(k.get_branches(db), {"branch_code": "Branch Code", "branch": "Branch Name"})
    with st.form("add_branch"):
        c1, c2 = st.columns(2)
        new_code = c1.text_input("New branch code (for example Branch21)")
        new_name = c2.text_input("New branch name (for example Philippines)")
        add_b = st.form_submit_button("Add branch")
    if add_b:
        try:
            added = k.add_branch(db, new_code, new_name, user["username"])
            st.success(f"{added} added. Next: create its user on the Users page, then import its file or start entering.")
        except ValueError as err:
            st.error(str(err))

    st.subheader("Import a branch file")
    st.caption('Upload one branch file: .xlsx with a sheet named "data", or .csv. Columns: Date, Metric, Metric Value. '
               "Entries already saved for the same date and metric are replaced.")
    branches = k.get_branches(db)
    code = st.selectbox("Branch for this file", branches["branch_code"], format_func=branch_label(branches),
                        key="import_branch")
    up = st.file_uploader("Branch file", type=["xlsx", "csv"], key="import_file")
    if up is not None:
        try:
            clean, problems = k.check_branch_file(db, k.read_branch_file(up, up.name))
            if up.name.split(".")[0].split("_")[0].lower() != code.lower():
                st.warning(f"The file name is {up.name} and the selected branch is {code}. Check that they match.")
            if len(clean):
                st.write(f"{len(clean):,} rows ready, from {clean['date'].min()} to {clean['date'].max()}, "
                         f"{clean['date'].nunique()} days.")
            else:
                st.error("No usable rows in this file.")
            for p in problems:
                st.warning(p)
            if len(clean) and st.button(f"Import into {code}", key="import_go"):
                result = k.import_entries(db, code, clean, user["username"])
                st.success(f"{code}: {result['rows']:,} rows imported. {result['added']:,} new, "
                           f"{result['replaced']:,} replaced.")
        except ValueError as err:
            st.error(str(err))
        except Exception:
            st.error("The file could not be read. Check that it is a normal .xlsx or .csv file.")
    st.subheader("Export")
    st.download_button("Download all entries as CSV", k.load_fact(db).to_csv(index=False), "entries.csv", "text/csv")
    st.subheader("Recent activity")
    st.dataframe(k.recent_log(db), use_container_width=True, hide_index=True)


def page_my_account(user):
    st.title("My Account")
    st.write(f"Username: **{user['username']}**  |  Name: {user['full_name']}  |  Role: {user['role']}"
             + (f"  |  Branch: {user['branch_code']}" if user["branch_code"] else ""))
    st.subheader("Change password")
    password_form(user, forced=False)


PAGE_FUNCS = {
    "Daily Entry": page_daily_entry, "My Branch": page_my_branch, "Main Dashboard": page_main_dashboard,
    "KPI Dashboard": page_kpi_dashboard, "Drill-down": page_drill_down,
    "Submission Check": page_submission_check, "Data Quality": page_data_quality,
    "Users": page_users, "Admin": page_admin, "My Account": page_my_account,
}


def main():
    if not HAS_OWNER:
        setup_page()
        return
    user = st.session_state.get("user")
    if not user:
        # After a page refresh the browser still has the session token in the address.
        token = st.query_params.get("s")
        user = k.get_session_user(db, token) if token else None
        if user:
            st.session_state["user"] = user
            st.session_state["token"] = token
        elif token:
            del st.query_params["s"]
    elif st.session_state.get("token") and st.query_params.get("s") != st.session_state["token"]:
        st.query_params["s"] = st.session_state["token"]
    if not user:
        login_page()
        return
    if user.get("must_change"):
        password_form(user, forced=True)
        return
    with st.sidebar:
        st.write(f"Signed in as **{user['full_name']}** ({user['role']})")
        page = st.radio("Go to", PAGES[user["role"]])
        if st.button("Sign out"):
            k.end_session(db, st.session_state.get("token"))
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.query_params.clear()
            st.rerun()
        st.caption(f"You stay signed in for {k.SESSION_HOURS} hours, or until you sign out. "
                   "Do not share the page address while signed in.")
    PAGE_FUNCS[page](user)


main()
