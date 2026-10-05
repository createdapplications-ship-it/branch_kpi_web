"""Company portal: Attendance and Branch KPI in one app, with one account per person.

Run on a PC:   streamlit run app.py        (uses a local SQLite file)
Run hosted:    set DATABASE_URL, ADMIN_USERNAME and ADMIN_PASSWORD as secrets (uses PostgreSQL)
"""
import os
from datetime import date, datetime

import pandas as pd
import streamlit as st

import kpi_logic as k
import att_logic as a

st.set_page_config(page_title="Company Portal", layout="wide", initial_sidebar_state="collapsed")

# Look of the portal: grey page, white cards and a floating menu box.
st.markdown(f"""
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {{display: none;}}
.block-container {{padding-top: 3.2rem; max-width: 1500px;}}
h1, h2, h3 {{font-family: "Segoe UI", Arial, sans-serif; font-weight: 600; letter-spacing: 0;}}
h1 {{font-size: 1.9rem;}}
/* cards */
div[class*="st-key-card_"], div[class*="st-key-menu_card"] {{
    background: #FFFFFF; border: 1px solid #E1E1E1; border-radius: 8px; padding: 1.4rem 1.6rem;
    box-shadow: 0 1px 3px rgba(0,0,0,.08);}}
/* top bar: portal name, drop-down menus and a breadcrumb line. Stays at the top while the page scrolls */
div[class*="st-key-menu_card"] {{position: sticky; top: 3.4rem; z-index: 90; padding: .45rem 1.4rem .55rem 1.4rem;
    border-radius: 0; border-width: 0 0 1px 0; box-shadow: 0 2px 8px rgba(0,0,0,.12);}}
div[class*="st-key-menu_card"] .brand {{font-size: 1.15rem; font-weight: 600; color: #1B1B1B;
    border-right: 2px solid #1B1B1B; padding-right: 1rem; white-space: nowrap;}}
div[class*="st-key-menu_card"] [data-testid="stPopover"] button,
div[class*="st-key-menu_card"] button[kind="tertiary"] {{border: none; background: transparent; color: #1B1B1B;
    font-size: .92rem; padding: .2rem .4rem;}}
div[class*="st-key-menu_card"] [data-testid="stPopover"] button:hover,
button[kind="tertiary"]:hover {{text-decoration: underline; color: #0F6CBD;}}
div[data-testid="stPopoverBody"] button[kind="tertiary"] {{justify-content: flex-start; width: 100%; color: #1B1B1B;}}
.crumb {{font-size: .9rem; color: #1B1B1B; padding-top: .35rem; border-top: 1px solid #EDEDED; margin-top: .3rem;}}
.crumb span {{color: #0F6CBD; text-decoration: underline;}}
/* colours set here as well, so the look does not depend on the config file */
.stApp {{background: #E9E9E9;}}
button[kind="primary"] {{background: #0F6CBD; border-color: #0F6CBD; color: #FFFFFF;}}
button[kind="primary"]:hover {{background: #0C5AA0; border-color: #0C5AA0; color: #FFFFFF;}}
/* dashboard: title band, stat tiles, chart panel titles, section bands */
.band {{background: #1F2A44; color: #FFFFFF; text-align: center; padding: .9rem 1rem .7rem; border-radius: 6px 6px 0 0;}}
.band-t {{font-size: 1.5rem; font-weight: 700; letter-spacing: .04em; text-transform: uppercase;}}
.band-s {{font-size: .85rem; opacity: .85; margin-top: .15rem;}}
.tiles {{display: flex; gap: 12px; margin: 12px 0 16px; flex-wrap: wrap;}}
.tile {{flex: 1 1 160px; background: #FFFFFF; border: 1px solid #E1E1E1; border-radius: 6px; overflow: hidden; text-align: center;}}
.tile-h {{color: #FFFFFF; font-size: .72rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; padding: .3rem .4rem;}}
.tile-v {{font-size: 1.9rem; font-weight: 700; padding-top: .45rem; line-height: 1.15;}}
.tile-n {{font-size: .78rem; color: #6B7280; padding: .1rem 0 .55rem;}}
.ptitle {{text-align: center; font-weight: 700; font-size: 1.05rem; color: #1B1B1B; margin-bottom: .3rem;}}
.sband {{color: #FFFFFF; font-weight: 700; text-align: center; padding: .5rem 1rem; border-radius: 6px 6px 0 0;
    margin-top: 1rem; letter-spacing: .02em;}}
[data-testid="stMetric"] {{background: #FFFFFF; border: 1px solid #E1E1E1; border-radius: 8px; padding: .8rem 1rem;}}
</style>
""", unsafe_allow_html=True)


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
a.TZ_NAME = cfg("APP_TIMEZONE", a.TZ_NAME)
PORTAL_NAME = cfg("PORTAL_NAME", "Company Portal")

# Data is kept in memory for a short time so each click does not reload every entry from the database.
# It is cleared straight after any save, import or reference change.
@st.cache_data(ttl=120, show_spinner=False)
def fact():
    return k.load_fact(db)


@st.cache_data(ttl=300, show_spinner=False)
def branch_list():
    return k.get_branches(db)


def refresh_data():
    fact.clear()
    branch_list.clear()


KPI_PAGES = {
    "employee": [],
    "branch": ["Daily Entry", "My Branch", "My Cluster"],
    "manager": ["Main Dashboard", "Quarter Ranking", "KPI Dashboard", "Drill-down"],
    "owner": ["Main Dashboard", "Quarter Ranking", "KPI Dashboard", "Drill-down", "Submission Check",
              "Data Quality", "Daily Entry", "Admin"],
}
ATT_PAGES = {
    "employee": ["My Attendance"],
    "branch": ["My Attendance"],
    "manager": ["My Attendance", "Attendance Today", "Attendance Report"],
    "owner": ["My Attendance", "Attendance Today", "Attendance Report", "Corrections"],
}


def sections_for(role):
    """The sections a role can open, and the pages in each."""
    out = {"Home": ["Home", "My Account"] + (["Users"] if role == "owner" else []),
           "Attendance": ATT_PAGES[role]}
    if KPI_PAGES[role]:
        out["Branch KPI"] = KPI_PAGES[role]
    return out


def go_to(section, page=None):
    """Open a section, on its first page unless a page is given."""
    st.session_state["dest"] = section
    st.session_state["nav"] = (section, page)


def xl_table(t, formats=None):
    """Show a table across the full width. Click a column header to sort."""
    rows = min(len(t), 20)
    st.dataframe(t.style.format(formats or {}, na_rep=""), use_container_width=True, hide_index=True,
                 height=38 + 35 * max(rows, 1))


def fmt_table(df, cols, formats=None):
    xl_table(df[list(cols)].rename(columns=cols), formats)


def card(key):
    """A white box, like a tile on the page."""
    return st.container(key="card_" + key)


def branch_label(branches):
    names = branches.set_index("branch_code")["branch"]
    return lambda c: f"{c} - {names[c]}"


# ---------------------------------------------------------------- sign-in
def setup_page():
    """Shown only when no owner account exists yet."""
    st.title("Company Portal: first-time setup")
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


def choose(section):
    st.session_state["dest"] = section


def landing_page():
    """The open main page. No sign-in here. Each link leads to the sign-in page."""
    st.title(PORTAL_NAME)
    st.caption("Choose where to go. You sign in with your own username and password.")
    c1, c2 = st.columns(2)
    with c1, card("land_att"):
        st.subheader("Attendance")
        st.write("Time in and time out each day, and see your own attendance record for the month.")
        st.button("Open Attendance", key="open_att", type="primary", on_click=choose, args=("Attendance",))
    with c2, card("land_kpi"):
        st.subheader("Branch KPI")
        st.write("Enter the daily values for your branch, and view the rankings, clusters and dashboards.")
        st.button("Open Branch KPI", key="open_kpi", type="primary", on_click=choose, args=("Branch KPI",))


def login_page():
    dest = st.session_state.get("dest", "Home")
    st.title(f"{dest}: sign in" if dest != "Home" else "Sign in")
    st.caption("One account works for both Attendance and Branch KPI.")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        try:
            user = k.check_login(db, username, password)
        except ValueError as err:
            st.error(str(err))
            return
        if user:
            st.session_state["user"] = user
            token = k.create_session(db, user["username"])
            st.session_state["token"] = token
            st.query_params["s"] = token      # keeps the sign-in after a page refresh
            st.rerun()
        else:
            st.error("Wrong username or password, or the account is not active.")
    st.caption("No account? Ask the owner to create one.")
    st.button("Back to the main page", key="back_home", on_click=lambda: st.session_state.pop("dest", None))


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
    branches = branch_list()
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
            refresh_data()
            st.success(f"Saved {saved} values for {day:%d %b %Y}." + (f" Removed {removed}." if removed else ""))
        except ValueError as err:
            st.error(str(err))


def page_my_branch(user):
    st.title("My Branch")
    df = fact()
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


def quarter_table(table, info, with_cluster=True):
    cols = {"rank": "Program Rank", "cluster_rank": "Cluster Rank", "branch": "Branch"}
    if with_cluster:
        cols["cluster"] = "Cluster"
    cols["adjusted"] = "Adjusted Value, QTD"
    for mth in info["months"]:
        cols[mth] = mth
    cols.update({"days_reported": "Days Reported", "prev_adjusted": info["prev_label"],
                 "prev_rank": "Previous Rank", "rank_change": "Rank Change"})
    formats = {"Program Rank": "{:.0f}", "Cluster Rank": "{:.0f}", "Adjusted Value, QTD": "{:,.1f}",
               "Days Reported": "{:.0f}", info["prev_label"]: "{:,.1f}", "Previous Rank": "{:.0f}",
               "Rank Change": "{:+.0f}"}
    formats.update({mth: "{:,.1f}" for mth in info["months"]})
    fmt_table(table, cols, formats)


def page_my_cluster(user):
    st.title("My Cluster")
    df = fact()
    branches = branch_list()
    row = branches[branches["branch_code"] == user["branch_code"]]
    if row.empty:
        st.error("Your account is not linked to a branch. Ask the dashboard owner.")
        return
    cluster = row.iloc[0]["cluster"]
    as_of = st.date_input("As of date", value=k.latest_data_date(df), max_value=date.today())
    table, info = k.quarter_ranking(df, as_of, branches)
    view = k.cluster_view(table, cluster)
    mine = view[view["branch_code"] == user["branch_code"]].iloc[0]
    clusters = k.cluster_summary(table)
    crow = clusters[clusters["cluster"] == cluster].iloc[0]
    st.caption(f"{cluster}, {info['label']} to date: {info['start']:%d %b} to {info['end']:%d %b %Y}. "
               f"Program Rank is counted across all {info['branches']} branches. "
               "You see the figures of the branches in your cluster only.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("My Adjusted Value, QTD", f"{mine['adjusted']:,.1f}" if pd.notna(mine["adjusted"]) else "No data")
    c2.metric("My program rank", f"{mine['rank']:.0f} of {info['ranked']}" if pd.notna(mine["rank"]) else "No data")
    c3.metric("My rank in the cluster", f"{mine['cluster_rank']:.0f} of {int(crow['reporting'])}"
              if pd.notna(mine["cluster_rank"]) else "No data")
    c4.metric("Cluster rank", f"{crow['cluster_rank']:.0f} of {int(clusters['cluster_rank'].notna().sum())}"
              if pd.notna(crow["cluster_rank"]) else "No data")
    st.subheader(f"{cluster} branches, {info['label']} to date")
    quarter_table(view, info, with_cluster=False)
    have = view.dropna(subset=["rank"])
    if len(have):
        st.bar_chart(have.set_index("branch")["adjusted"])


def page_quarter_ranking(user):
    st.title("Quarter Ranking")
    df = fact()
    branches = branch_list()
    c1, c2 = st.columns(2)
    as_of = c1.date_input("As of date", value=k.latest_data_date(df), max_value=date.today())
    table, info = k.quarter_ranking(df, as_of, branches)
    clusters = k.cluster_summary(table)
    pick = c2.selectbox("Cluster", ["All clusters"] + sorted(table["cluster"].dropna().unique()))
    st.caption(f"{info['label']} to date: {info['start']:%d %b} to {info['end']:%d %b %Y}. "
               f"Program Rank is counted across all {info['branches']} branches. "
               f"Previous figures are for the full {info['prev_label']}.")
    top = table.dropna(subset=["rank"])
    topc = clusters.dropna(subset=["cluster_rank"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Adjusted Value, QTD", f"{top['adjusted'].sum():,.1f}")
    m2.metric("Top branch", top.iloc[0]["branch"] if len(top) else "No data")
    m3.metric("Top cluster", topc.iloc[0]["cluster"] if len(topc) else "No data")
    m4.metric("Branches reporting", f"{info['ranked']} of {info['branches']}")
    st.subheader("Clusters")
    fmt_table(clusters, {"cluster_rank": "Rank", "cluster": "Cluster", "adjusted": "Adjusted Value, QTD",
                         "share": "Share of Program", "avg_per_branch": "Avg per Branch",
                         "reporting": "Branches Reporting", "top_branch": "Top Branch", "best_rank": "Best Program Rank"},
              {"Rank": "{:.0f}", "Adjusted Value, QTD": "{:,.1f}", "Share of Program": "{:.1%}",
               "Avg per Branch": "{:,.1f}", "Branches Reporting": "{:.0f}", "Best Program Rank": "{:.0f}"})
    if len(topc):
        st.bar_chart(topc.set_index("cluster")["adjusted"])
    st.subheader("Branches" if pick == "All clusters" else f"{pick} branches")
    view = table if pick == "All clusters" else k.cluster_view(table, pick)
    quarter_table(view, info)
    st.download_button("Download quarter ranking as CSV", view.to_csv(index=False), "quarter_ranking.csv", "text/csv")


# ---------------------------------------------------------------- dashboard building blocks
BLUE, GREY, GREEN, AMBER, RED, NAVY = "#0F6CBD", "#9AA5B1", "#2E8B57", "#D9822B", "#C0392B", "#1F2A44"
CLUSTER_COLOURS = ["#0F6CBD", "#2E8B57", "#D9822B", "#7A5AA6", "#3AA6B9", "#9AA5B1"]


def title_band(title, subtitle):
    st.markdown(f'<div class="band"><div class="band-t">{title}</div><div class="band-s">{subtitle}</div></div>',
                unsafe_allow_html=True)


def section_band(text, colour=NAVY):
    st.markdown(f'<div class="sband" style="background:{colour}">{text}</div>', unsafe_allow_html=True)


def tiles(items):
    """A row of stat tiles. items: list of (label, value, note, colour)."""
    cells = "".join(
        f'<div class="tile"><div class="tile-h" style="background:{c}">{label}</div>'
        f'<div class="tile-v" style="color:{c}">{value}</div><div class="tile-n">{note}</div></div>'
        for label, value, note, c in items)
    st.markdown(f'<div class="tiles">{cells}</div>', unsafe_allow_html=True)


def panel(key, title):
    """A white chart panel with a centred title."""
    box = st.container(key="card_" + key)
    box.markdown(f'<div class="ptitle">{title}</div>', unsafe_allow_html=True)
    return box


def chart(data, spec):
    spec = {"config": {"view": {"stroke": None}, "axis": {"labelFontSize": 12, "titleFontSize": 12, "grid": True,
                                                           "gridColor": "#EEEEEE"}}, **spec}
    st.vega_lite_chart(data, spec, use_container_width=True)


def colour_status(value):
    return {"Submitted": f"color: {GREEN}; font-weight: 600", "Partial": f"color: {AMBER}; font-weight: 600",
            "Not submitted": f"color: {RED}; font-weight: 600"}.get(value, "")


def page_main_dashboard(user):
    df = fact()
    branches = branch_list()
    as_of = st.date_input("As of date", value=k.latest_data_date(df), max_value=date.today())
    table, info = k.mtd_compare(df, as_of, branches)
    title_band("Branch KPI Dashboard",
               f"Month to date {info['cur_start']:%d %b} to {info['cur_end']:%d %b %Y} &nbsp;|&nbsp; compared with "
               f"{info['prev_start']:%d %b} to {info['prev_end']:%d %b %Y}")
    top = table.dropna(subset=["rank"])
    by_cluster = (top.groupby("cluster", as_index=False)["adjusted"].sum()
                  .sort_values("adjusted", ascending=False).reset_index(drop=True))
    change = info["change_pct"]
    reporting, total = len(top), len(branches)
    tiles([
        ("Adjusted Value, MTD", f"{info['cur_total']:,.1f}", "All branches", BLUE),
        ("Change vs previous month", f"{change:+.1%}" if change is not None else "n/a",
         f"Previous: {info['prev_total']:,.1f}", GREY if change is None else (GREEN if change >= 0 else RED)),
        ("Top branch", top.iloc[0]["branch"] if len(top) else "No data",
         f"{top.iloc[0]['adjusted']:,.1f}" if len(top) else "", BLUE),
        ("Top cluster", by_cluster.iloc[0]["cluster"] if len(by_cluster) else "No data",
         f"{by_cluster.iloc[0]['adjusted']:,.1f}" if len(by_cluster) else "", BLUE),
        ("Branches reporting", f"{reporting} of {total}", "This month",
         GREEN if reporting == total else AMBER),
    ])
    if not len(top):
        st.info("No entries yet for this month.")
        return

    g1, g2 = st.columns([3, 2])
    with g1, panel("rank", "Adjusted Value by Branch"):
        chart(top[["branch", "cluster", "adjusted", "rank"]], {
            "mark": {"type": "bar", "color": BLUE, "cornerRadiusEnd": 2},
            "encoding": {
                "y": {"field": "branch", "type": "nominal", "sort": "-x", "title": None},
                "x": {"field": "adjusted", "type": "quantitative", "title": "Adjusted Value"},
                "tooltip": [{"field": "branch", "title": "Branch"}, {"field": "cluster", "title": "Cluster"},
                            {"field": "rank", "title": "Rank"},
                            {"field": "adjusted", "title": "Adjusted Value", "format": ",.1f"}]},
            "height": {"step": 20}})
    with g2, panel("cluster", "Share by Cluster"):
        chart(by_cluster, {
            "mark": {"type": "arc", "innerRadius": 70},
            "encoding": {
                "theta": {"field": "adjusted", "type": "quantitative", "stack": True},
                "color": {"field": "cluster", "type": "nominal", "scale": {"range": CLUSTER_COLOURS},
                          "legend": {"title": None, "orient": "bottom"}},
                "order": {"field": "adjusted", "type": "quantitative", "sort": "descending"},
                "tooltip": [{"field": "cluster", "title": "Cluster"},
                            {"field": "adjusted", "title": "Adjusted Value", "format": ",.1f"}]},
            "height": 320})

    cur = k.daily_breakdown(df, info["cur_start"], info["cur_end"])
    prev = k.daily_breakdown(df, info["prev_start"], info["prev_end"])
    g3, g4 = st.columns(2)
    with g3, panel("daily", "Daily Adjusted Value"):
        chart(cur.assign(day=cur["date"].dt.strftime("%d"))[["day", "adjusted"]], {
            "mark": {"type": "bar", "color": BLUE},
            "encoding": {
                "x": {"field": "day", "type": "ordinal", "sort": None, "title": "Day of month",
                      "axis": {"labelAngle": 0}},
                "y": {"field": "adjusted", "type": "quantitative", "title": "Adjusted Value"},
                "tooltip": [{"field": "day", "title": "Date"},
                            {"field": "adjusted", "title": "Adjusted Value", "format": ",.1f"}]},
            "height": 280})
    with g4, panel("compare", "Running Total: This Month vs Previous Month"):
        lines = pd.concat([
            pd.DataFrame({"day": cur["date"].dt.day, "total": cur["running_total"], "series": "This month"}),
            pd.DataFrame({"day": prev["date"].dt.day, "total": prev["running_total"], "series": "Previous month"})])
        chart(lines, {
            "mark": {"type": "line", "point": True, "strokeWidth": 2.5},
            "encoding": {
                "x": {"field": "day", "type": "quantitative", "title": "Day of month", "axis": {"tickMinStep": 1}},
                "y": {"field": "total", "type": "quantitative", "title": "Running total"},
                "color": {"field": "series", "type": "nominal",
                          "scale": {"domain": ["This month", "Previous month"], "range": [BLUE, GREY]},
                          "legend": {"title": None, "orient": "bottom"}},
                "strokeDash": {"field": "series", "type": "nominal",
                               "scale": {"domain": ["This month", "Previous month"], "range": [[1, 0], [5, 4]]},
                               "legend": None},
                "tooltip": [{"field": "series", "title": "Period"}, {"field": "day", "title": "Day"},
                            {"field": "total", "title": "Running total", "format": ",.1f"}]},
            "height": 280})

    if user["role"] in ("manager", "owner"):
        day = k.last_working_day(as_of)
        sub = k.submission_check(db, day)
        missing = sub[sub["status"] != "Submitted"]
        if len(missing):
            section_band(f"Needs attention: {len(missing)} branch(es) not fully submitted for {day:%a %d %b %Y}", RED)
            t = missing.rename(columns={"branch_code": "Branch Code", "branch": "Branch", "entered": "Metrics Entered",
                                        "expected": "Expected", "status": "Status"})[
                ["Branch Code", "Branch", "Metrics Entered", "Expected", "Status"]]
            st.dataframe(t.style.map(colour_status, subset=["Status"]), use_container_width=True, hide_index=True,
                         height=38 + 35 * min(len(t), 10))
        else:
            section_band(f"All branches submitted for {day:%a %d %b %Y}", GREEN)

    section_band("Ranking, month to date")
    fmt_table(table,
              {"rank": "Rank", "branch": "Branch", "cluster": "Cluster", "adjusted": "Adjusted Value",
               "prev_adjusted": "Previous Month", "change_pct": "Change %", "prev_rank": "Previous Rank",
               "rank_change": "Rank Change", "days_reported": "Days Reported"},
              {"Rank": "{:.0f}", "Adjusted Value": "{:,.1f}", "Previous Month": "{:,.1f}", "Change %": "{:+.1%}",
               "Previous Rank": "{:.0f}", "Rank Change": "{:+.0f}", "Days Reported": "{:.0f}"})


def page_kpi_dashboard(user):
    st.title("KPI Dashboard")
    df = fact()
    branches = branch_list()
    latest = k.latest_data_date(df)
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("From", value=latest.replace(day=1))
    end = c2.date_input("To", value=latest)
    metric = c3.selectbox("Metric", ["All metrics"] + list(k.get_metrics(db)["metric"]))
    st.caption("Figures refresh within 2 minutes, and at once after you save or import.")
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
    if True:
        fmt_table(r, {"rank": "Rank", "branch": "Branch", "adjusted": "Adjusted Value", "share": "Share of Company",
                      "days_reported": "Days Reported", "avg_per_day": "Avg per Day", "last_date": "Last Reported"},
                  {"Rank": "{:.0f}", "Adjusted Value": "{:,.1f}", "Share of Company": "{:.1%}",
                   "Days Reported": "{:.0f}", "Avg per Day": "{:,.1f}", "Last Reported": "{:%d %b %Y}"})
    if len(have):
        st.subheader("Adjusted Value by branch")
        st.bar_chart(have.set_index("branch")["adjusted"])
    st.download_button("Download ranking as CSV", r.to_csv(index=False), "ranking.csv", "text/csv")


def page_drill_down(user):
    st.title("Drill-down")
    df = fact()
    branches = branch_list()
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
    st.subheader("By metric")
    fmt_table(k.metric_breakdown(df, start, end, code),
              {"metric": "Metric", "multiplier": "Multiplier", "metric_value": "Metric Value",
               "adjusted": "Adjusted Value", "share": "Share"},
              {"Multiplier": "{:.1f}", "Metric Value": "{:,.0f}", "Adjusted Value": "{:,.1f}", "Share": "{:.1%}"})
    st.subheader("By day")
    st.bar_chart(d.set_index("date")["adjusted"])


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
    branches = branch_list()
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
        role = c1.selectbox("Role (employee = Attendance only)", list(k.ROLES))
        code = c2.selectbox("Branch (needed for the branch role, optional for others)",
                            ["(none)"] + list(branches["branch_code"]))
        add = st.form_submit_button("Create user")
    if add:
        try:
            temp = k.new_temp_password()
            name = k.create_user(db, username, full_name, role, None if code == "(none)" else code, temp,
                                 by=user["username"])
            st.success(f"User {name} created. Temporary password: {temp}")
            st.caption("Give this password to the user. It is shown only once. They must change it at first sign-in.")
        except ValueError as err:
            st.error(str(err))

    st.subheader("Add many users from a file")
    st.caption("Upload a .csv with the columns Username, Full Name, Role, Branch. "
               "Role is employee, branch, manager or owner. Branch can be blank except for the branch role.")
    template = "Username,Full Name,Role,Branch\njuan.cruz,Juan Cruz,employee,Branch01\nbranch01,Branch 01 encoder,branch,Branch01\n"
    st.download_button("Download the user list template", template, "user_list_template.csv", "text/csv")
    up = st.file_uploader("User list (.csv)", type=["csv"], key="bulk_users")
    if up is not None and st.button("Create the users in this file", key="bulk_go"):
        try:
            created, problems = k.bulk_create_users(db, pd.read_csv(up, dtype=str), by=user["username"])
            st.success(f"{len(created)} user(s) created. {len(problems)} row(s) skipped.")
            if len(created):
                xl_table(created)
                st.download_button("Download the temporary passwords (shown only once)", created.to_csv(index=False),
                                   "temporary_passwords.csv", "text/csv")
                st.caption("Hand each password to its user, then delete the downloaded file.")
            if len(problems):
                xl_table(problems)
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
    st.subheader("Metrics and multipliers")
    st.warning("Changing a multiplier changes every past Adjusted Value. Export a copy of the data first.")
    m = k.get_metrics(db)
    view = m.assign(active=m["active"].map({1: "Yes", 0: "No"})).rename(
        columns={"metric": "Metric", "multiplier": "Multiplier", "active": "Active"})
    edited = st.data_editor(view, disabled=["Metric", "Active"], hide_index=True, key="mult_editor")
    st.caption(f"{int((m['active'] == 1).sum())} active metrics. Branches are asked for the active ones only.")
    if st.button("Save multipliers"):
        changed = 0
        for (_, old), (_, new) in zip(m.iterrows(), edited.iterrows()):
            if pd.notna(new["Multiplier"]) and float(new["Multiplier"]) != float(old["multiplier"]):
                k.set_multiplier(db, old["metric"], new["Multiplier"], user["username"])
                changed += 1
        refresh_data()
        st.success(f"{changed} multiplier(s) updated.")
    with st.form("add_metric"):
        c1, c2 = st.columns(2)
        new_metric = c1.text_input("New metric name")
        new_mult = c2.text_input("Its multiplier (for example 0.8)")
        add_m = st.form_submit_button("Add metric")
    if add_m:
        try:
            st.success(f"Metric {k.add_metric(db, new_metric, new_mult, user['username'])} added.")
        except ValueError as err:
            st.error(str(err))
    with st.form("metric_active"):
        target_m = st.selectbox("Metric to change", list(m["metric"]))
        action_m = st.radio("Metric action", ["Deactivate metric", "Activate metric"])
        go_m = st.form_submit_button("Apply to metric")
    if go_m:
        try:
            k.set_metric_active(db, target_m, action_m == "Activate metric", user["username"])
            st.success(f"{target_m}: done. A deactivated metric keeps its history and is no longer asked for.")
        except ValueError as err:
            st.error(str(err))

    st.subheader("Branches")
    fmt_table(branch_list(), {"branch_code": "Branch Code", "branch": "Branch Name", "cluster": "Cluster"})
    with st.form("add_branch"):
        c1, c2, c3 = st.columns(3)
        new_code = c1.text_input("New branch code (for example Branch21)")
        new_name = c2.text_input("New branch name (for example Philippines)")
        new_cluster = c3.text_input("Cluster (blank = set from the branch number)")
        add_b = st.form_submit_button("Add branch")
    with st.form("set_cluster"):
        c1, c2 = st.columns(2)
        move_code = c1.selectbox("Branch to move", list(branch_list()["branch_code"]))
        move_to = c2.text_input("Move to cluster (for example Cluster02)")
        move_b = st.form_submit_button("Change cluster")
    if move_b:
        try:
            k.set_cluster(db, move_code, move_to, user["username"])
            refresh_data()
            st.success(f"{move_code} is now in {move_to.strip()}.")
        except ValueError as err:
            st.error(str(err))
    if add_b:
        try:
            added = k.add_branch(db, new_code, new_name, user["username"], new_cluster)
            refresh_data()
            st.success(f"{added} added. Next: create its user on the Users page, then import its file or start entering.")
        except ValueError as err:
            st.error(str(err))

    st.subheader("Import a branch file")
    st.caption('Upload one branch file: .xlsx with a sheet named "data", or .csv. Columns: Date, Metric, Metric Value. '
               "Entries already saved for the same date and metric are replaced.")
    branches = branch_list()
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
                refresh_data()
                st.success(f"{code}: {result['rows']:,} rows imported. {result['added']:,} new, "
                           f"{result['replaced']:,} replaced.")
        except ValueError as err:
            st.error(str(err))
        except Exception:
            st.error("The file could not be read. Check that it is a normal .xlsx or .csv file.")
    st.subheader("Export")
    st.download_button("Download all entries as CSV", fact().to_csv(index=False), "entries.csv", "text/csv")
    st.subheader("Remove sample data")
    st.caption("Deletes the sample entries loaded when the app first started. Entries typed or imported by users are kept. "
               "Do this once, before the real branch files are imported.")
    sure = st.checkbox("I understand this cannot be undone", key="rm_sample_ok")
    if st.button("Remove sample entries", key="rm_sample") and sure:
        removed = k.remove_sample_data(db, user["username"])
        refresh_data()
        st.success(f"{removed:,} sample entries removed.")
    st.subheader("Recent activity")
    xl_table(k.recent_log(db).rename(columns={"at": "When", "username": "User", "action": "Action", "detail": "Detail"}))


def page_my_account(user):
    st.title("My Account")
    st.write(f"Username: **{user['username']}**  |  Name: {user['full_name']}  |  Role: {user['role']}"
             + (f"  |  Branch: {user['branch_code']}" if user["branch_code"] else ""))
    st.subheader("Change password")
    password_form(user, forced=False)


# ---------------------------------------------------------------- home and attendance
def page_home(user):
    st.title(PORTAL_NAME)
    st.write(f"Signed in as **{user['full_name']}**.")
    secs = sections_for(user["role"])
    c1, c2 = st.columns(2)
    with c1, card("home_att"):
        st.subheader("Attendance")
        state, rec = a.status(db, user["username"])
        st.write({"in": "You are timed in.", "out": "You are not timed in.",
                  "no_time_out": "An earlier time in was never closed."}[state])
        st.button("Open Attendance", key="home_att", type="primary", on_click=go_to, args=("Attendance",))
    with c2, card("home_kpi"):
        st.subheader("Branch KPI")
        if "Branch KPI" in secs:
            st.write("Enter daily values and view the rankings and dashboards.")
            st.button("Open Branch KPI", key="home_kpi", type="primary", on_click=go_to, args=("Branch KPI",))
        else:
            st.write("Your account does not have Branch KPI access. Ask the owner if you need it.")


def _hm(v):
    return "" if v is None or pd.isna(v) else f"{v:%H:%M}"


def att_table(r, with_name=True):
    t = pd.DataFrame({"Date": r["work_date"]})
    if with_name:
        t["Name"] = r["full_name"]
        t["Branch"] = r["branch_code"]
    t["Time In"] = [_hm(v) for v in r["in_local"]]
    t["Time Out"] = [_hm(v) for v in r["out_local"]]
    t["Hours"] = r["hours"]
    t["Status"] = r["status"]
    t["Note"] = r["note"].fillna("")
    xl_table(t, {"Hours": "{:.2f}"})


def page_my_attendance(user):
    st.title("My Attendance")
    name = user["username"]
    state, rec = a.status(db, name)
    today = a.local_today()
    if state == "in":
        st.success(f"Timed in since {a.to_local(rec['time_in']):%H:%M on %d %b}.")
    elif state == "no_time_out":
        st.warning(f"Your time in on {rec['work_date']} was never closed. Ask the owner to correct it. "
                   "You can still time in for today.")
    else:
        st.info("You are not timed in.")
    c1, c2 = st.columns(2)
    try:
        if c1.button("Time In", key="btn_time_in", disabled=state == "in"):
            a.time_in(db, name)
            st.rerun()
        if c2.button("Time Out", key="btn_time_out", disabled=state != "in"):
            a.time_out(db, name)
            st.rerun()
    except ValueError as err:
        st.error(str(err))
    st.caption(f"Times are shown in {a.TZ_NAME} time. Today is {today:%a %d %b %Y}.")
    month = a.records(db, today.replace(day=1), today, username=name)
    m1, m2, m3 = st.columns(3)
    m1.metric("Days present this month", f"{month['work_date'].nunique()}")
    m2.metric("Hours this month", f"{month['hours'].sum():.1f}")
    m3.metric("Hours today", f"{month.loc[month['work_date'] == str(today), 'hours'].sum():.1f}")
    st.subheader("This month")
    if len(month):
        att_table(month.iloc[::-1], with_name=False)
    else:
        st.info("No attendance records yet this month.")


def page_attendance_today(user):
    st.title("Attendance Today")
    branches = branch_list()
    c1, c2 = st.columns(2)
    day = c1.date_input("Date", value=a.local_today(), max_value=a.local_today())
    pick = c2.selectbox("Branch", ["All branches"] + list(branches["branch_code"]))
    b = a.today_board(db, day)
    if pick != "All branches":
        b = b[b["branch_code"] == pick]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("People", f"{len(b)}")
    m2.metric("In", f"{int((b['status'] == 'In').sum())}")
    m3.metric("Out", f"{int((b['status'] == 'Out').sum())}")
    m4.metric("Not in", f"{int((b['status'] == 'Not in').sum())}")
    t = pd.DataFrame({"Name": b["full_name"], "Branch": b["branch_code"].fillna(""), "Status": b["status"],
                      "First In": [_hm(v) for v in b["first_in"]], "Last Out": [_hm(v) for v in b["last_out"]],
                      "Hours": b["hours"]})
    xl_table(t, {"Hours": "{:.2f}"})
    st.caption(f"Times are shown in {a.TZ_NAME} time.")


def page_attendance_report(user):
    st.title("Attendance Report")
    today = a.local_today()
    c1, c2 = st.columns(2)
    start = c1.date_input("From", value=today.replace(day=1))
    end = c2.date_input("To", value=today)
    if start > end:
        st.error("From must be on or before To.")
        return
    r = a.report(db, start, end)
    m1, m2, m3 = st.columns(3)
    m1.metric("People with attendance", f"{int((r['days_present'] > 0).sum())} of {len(r)}")
    m2.metric("Total hours", f"{r['hours'].sum():,.1f}")
    m3.metric("Records with no time out", f"{int(r['no_time_out'].sum())}")
    fmt_table(r, {"full_name": "Name", "branch_code": "Branch", "role": "Role", "days_present": "Days Present",
                  "hours": "Hours", "avg_hours": "Avg Hours per Day", "no_time_out": "No Time Out"},
              {"Hours": "{:,.2f}", "Avg Hours per Day": "{:.2f}"})
    st.download_button("Download the summary as CSV", r.to_csv(index=False), "attendance_summary.csv", "text/csv")
    detail = a.records(db, start, end)
    if len(detail):
        st.subheader("All records")
        att_table(detail)
        out = detail[["work_date", "username", "full_name", "branch_code", "in_local", "out_local", "hours",
                      "status", "note", "edited_by"]]
        st.download_button("Download all records as CSV", out.to_csv(index=False), "attendance_records.csv", "text/csv")


def _parse_time(text, label, required=True):
    text = (text or "").strip()
    if not text:
        if required:
            raise ValueError(f"Enter the {label} as YYYY-MM-DD HH:MM.")
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError(f"The {label} must look like 2026-10-05 08:30.")


def page_corrections(user):
    st.title("Corrections")
    st.caption(f"Fix a record or add a missed one. Every correction needs a reason and is written to the activity log. "
               f"Times are in {a.TZ_NAME} time.")
    today = a.local_today()
    c1, c2 = st.columns(2)
    start = c1.date_input("From", value=today.replace(day=1))
    end = c2.date_input("To", value=today)
    r = a.records(db, start, end)
    st.subheader("Change a record")
    if r.empty:
        st.info("No records in this period.")
    else:
        att_table(r)
        labels = {row["id"]: f"{row['work_date']} {row['full_name']} in {_hm(row['in_local'])} "
                             f"out {_hm(row['out_local']) or 'none'} ({row['status']})" for _, row in r.iterrows()}
        with st.form("fix_record"):
            rid = st.selectbox("Record", list(labels), format_func=lambda x: labels[x])
            f1, f2 = st.columns(2)
            new_in = f1.text_input("Correct time in (YYYY-MM-DD HH:MM)")
            new_out = f2.text_input("Correct time out (YYYY-MM-DD HH:MM, blank = still in)")
            why = st.text_input("Reason for the change")
            fix = st.form_submit_button("Save correction")
        if fix:
            try:
                a.correct_record(db, rid, _parse_time(new_in, "time in"), _parse_time(new_out, "time out", False),
                                 why, user["username"])
                st.success("Record corrected.")
            except ValueError as err:
                st.error(str(err))
    st.subheader("Add a missed record")
    users = k.list_users(db)
    with st.form("add_record"):
        who = st.selectbox("Person", list(users[users["active"].astype(int) == 1]["username"]))
        g1, g2 = st.columns(2)
        add_in = g1.text_input("Time in (YYYY-MM-DD HH:MM)")
        add_out = g2.text_input("Time out (YYYY-MM-DD HH:MM)")
        add_why = st.text_input("Reason for adding it")
        add = st.form_submit_button("Add record")
    if add:
        try:
            a.add_record(db, who, _parse_time(add_in, "time in"), _parse_time(add_out, "time out"),
                         add_why, user["username"])
            st.success("Record added.")
        except ValueError as err:
            st.error(str(err))


PAGE_FUNCS = {
    "Home": page_home, "My Attendance": page_my_attendance, "Attendance Today": page_attendance_today,
    "Attendance Report": page_attendance_report, "Corrections": page_corrections,
    "Daily Entry": page_daily_entry, "My Branch": page_my_branch, "Main Dashboard": page_main_dashboard,
    "KPI Dashboard": page_kpi_dashboard, "Drill-down": page_drill_down,
    "Submission Check": page_submission_check, "Data Quality": page_data_quality,
    "Users": page_users, "Admin": page_admin, "My Account": page_my_account,
    "My Cluster": page_my_cluster, "Quarter Ranking": page_quarter_ranking,
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
        if st.session_state.get("dest"):
            login_page()
        else:
            landing_page()
        return
    if user.get("must_change"):
        password_form(user, forced=True)
        return
    secs = sections_for(user["role"])
    # The open page is kept in the address too, so a refresh returns to the same page.
    section, page = st.session_state.get("nav") or (
        st.query_params.get("sec") or st.session_state.get("dest"), st.query_params.get("pg"))
    if section not in secs:
        section = "Home"
    if page not in secs[section]:
        page = secs[section][0]
    st.session_state["nav"] = (section, page)
    if st.query_params.get("pg") != page or st.query_params.get("sec") != section:
        st.query_params["sec"] = section
        st.query_params["pg"] = page
    with st.container(key="menu_card"):
        menus = [n for n in secs if n != "Home"]
        cols = st.columns([2.4, 0.9] + [1.5] * len(menus) + [max(0.5, 5.2 - 1.5 * len(menus)), 2.2, 1.1],
                          vertical_alignment="center")
        cols[0].markdown(f'<div class="brand">{PORTAL_NAME}</div>', unsafe_allow_html=True)
        cols[1].button("Home", key="nav_home", type="tertiary", on_click=go_to, args=("Home", "Home"))
        for i, name in enumerate(menus):
            with cols[2 + i].popover(name):
                for p in secs[name]:
                    st.button(p, key=f"nav_{name}_{p}", type="tertiary", on_click=go_to, args=(name, p))
        with cols[-2].popover(user["full_name"]):
            st.caption(f"Role: {user['role']}")
            for p in secs["Home"][1:]:
                st.button(p, key=f"nav_Home_{p}", type="tertiary", on_click=go_to, args=("Home", p))
            out = st.button("Sign out", key="nav_sign_out")
        trail = ["Home"] if section == "Home" and page == "Home" else (
            ["Home", page] if section == "Home" else ["Home", section, page])
        st.markdown('<div class="crumb">' + " &nbsp;/&nbsp; ".join(
            f"<b>{t}</b>" if i == len(trail) - 1 else f"<span>{t}</span>" for i, t in enumerate(trail)) + "</div>",
            unsafe_allow_html=True)
        if out:
            k.end_session(db, st.session_state.get("token"))
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.session_state.pop("dest", None)
            st.session_state.pop("nav", None)
            st.query_params.clear()
            st.rerun()
    PAGE_FUNCS[page](user)
    st.caption(f"You stay signed in for {k.SESSION_HOURS} hours, or until you sign out. "
               "Do not share the page address while signed in.")


main()
