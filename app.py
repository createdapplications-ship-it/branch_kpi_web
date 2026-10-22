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
import hr_logic as h
import payroll_logic as p
import crm_logic as c

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
/* top bar: dark band with the portal name and drop-down menus. Stays at the top while the page scrolls */
div[class*="st-key-menu_card"] {{position: sticky; top: 3.4rem; z-index: 90; background: #1F2A44; border: none;
    border-radius: 8px; padding: .35rem 1.2rem; box-shadow: 0 3px 10px rgba(0,0,0,.22); gap: 0;}}
div[class*="st-key-menu_card"] [data-testid="stMarkdownContainer"] {{margin: 0;}}
div[class*="st-key-menu_card"] [data-testid="stMarkdownContainer"] p {{margin: 0;}}
div[class*="st-key-menu_card"] .brand {{display: flex; align-items: center; gap: .55rem; font-size: 1.15rem;
    font-weight: 700; color: #FFFFFF; white-space: nowrap; line-height: 2.2rem;}}
div[class*="st-key-menu_card"] .brand .dot {{width: .8rem; height: .8rem; border-radius: 2px; background: #5BB0F0;
    display: inline-block;}}
div[class*="st-key-menu_card"] button, div[class*="st-key-menu_card"] button p,
div[class*="st-key-menu_card"] button svg {{color: #FFFFFF !important; fill: #FFFFFF;}}
div[class*="st-key-menu_card"] button {{border: none !important; background: transparent !important;
    font-size: .85rem; padding: .2rem .45rem; min-height: 1.9rem;}}
div[class*="st-key-menu_card"] button p {{font-size: .85rem;}}
div[class*="st-key-menu_card"] button:hover {{background: rgba(255,255,255,.12) !important;}}
div[data-testid="stPopoverBody"] {{min-width: 13rem; padding: .6rem .7rem;}}
div[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] {{gap: .1rem;}}
div[data-testid="stPopoverBody"] button[kind="tertiary"] {{justify-content: flex-start; width: 100%; color: #1B1B1B;
    padding: .25rem .5rem; border-radius: 4px;}}
div[data-testid="stPopoverBody"] button[kind="tertiary"]:hover {{background: #EEF4FB; color: #0F6CBD;}}
.crumb {{font-size: .88rem; color: #1B1B1B; background: #FFFFFF; border: 1px solid #E1E1E1; border-radius: 6px;
    padding: .4rem 1rem; margin: .1rem 0 .4rem;}}
.crumb span {{color: #0F6CBD;}}
.crumb i {{font-style: normal; color: #9AA5B1; padding: 0 .55rem;}}
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
    h.init_hr(db)
    p.init_payroll(db)
    c.init_crm(db)
    return db, has_owner


# The key that encrypts salary and pay data. Kept in the app secrets, never in the code.
os.environ["SALARY_KEY"] = cfg("SALARY_KEY", "") or ""


db, HAS_OWNER = get_db()
a.TZ_NAME = cfg("APP_TIMEZONE", a.TZ_NAME)
PORTAL_NAME = cfg("PORTAL_NAME", "Company Portal")

# Every module of the portal: shown as a card on the main page and in the menu bar. Each has its own colour.
MODULES = [
    ("Attendance", "Time in and out, schedules, correction and overtime requests, and leave.", "#1C7C8C"),
    ("Branch KPI", "Daily branch entries, rankings, clusters and dashboards.", "#0F6CBD"),
    ("HR", "Employee records, schedules, leave balances and holidays.", "#7A5AA6"),
    ("Payroll", "Pay runs from attendance, bonuses from targets, payslips and 13th month.", "#2E8B57"),
    ("CRM", "Clients, call-backs, assignments and the link to Branch KPI.", "#B5651D"),
]
MOD_COLOUR = {"Home": "#1F2A44", **{m[0]: m[2] for m in MODULES}}
CUR = {"colour": "#1F2A44"}   # colour of the section that is open


def _key(name):
    return name.replace(" ", "_")


st.markdown("<style>" + "".join(
    f'''div[class*="st-key-card_mod_{_key(n)}"] {{border-top: 6px solid {col} !important;}}
div[class*="st-key-card_mod_{_key(n)}"] h3 {{color: {col};}}
div[class*="st-key-card_mod_{_key(n)}"] button[kind="primary"] {{background: {col}; border-color: {col};}}
div[class*="st-key-navsec_{_key(n)}"] button p::before {{content: ""; display: inline-block; width: .55rem; height: .55rem;
    border-radius: 2px; background: {col}; margin-right: .45rem; vertical-align: .05rem; filter: brightness(1.35);}}
''' for n, _, col in MODULES) + "</style>", unsafe_allow_html=True)

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
    "employee": [], "hr": [], "payroll": [],
    "branch": ["Daily Entry", "My Branch", "My Cluster"],
    "supervisor": ["Daily Entry", "My Branch", "My Cluster"],
    "manager": ["Main Dashboard", "Quarter Ranking", "KPI Dashboard", "Drill-down"],
    "owner": ["Main Dashboard", "Quarter Ranking", "KPI Dashboard", "Drill-down", "Submission Check",
              "Data Quality", "Daily Entry", "Admin"],
}
ATT_PAGES = {
    "employee": ["My Attendance", "My Requests"],
    "branch": ["My Attendance", "My Requests"],
    "supervisor": ["My Attendance", "My Requests", "Approvals", "Attendance Today", "Attendance Report"],
    "hr": ["My Attendance", "My Requests", "Approvals", "Attendance Today", "Attendance Report", "Corrections"],
    "payroll": ["My Attendance", "My Requests", "Attendance Report"],
    "manager": ["My Attendance", "My Requests", "Approvals", "Attendance Today", "Attendance Report"],
    "owner": ["My Attendance", "My Requests", "Approvals", "Attendance Today", "Attendance Report", "Corrections"],
}
HR_PAGES = {"hr": ["Employees", "Schedules", "Leave and Holidays"], "owner": ["Employees", "Schedules", "Leave and Holidays"]}
PAY_PAGES = {"payroll": ["Pay Runs", "Rates and Allowances", "Targets and Bonus Rules", "13th Month", "Pay Settings"],
             "owner": ["Pay Runs", "Rates and Allowances", "Targets and Bonus Rules", "13th Month", "Pay Settings"]}
CRM_PAGES = {"employee": ["My Clients", "Call List"], "branch": ["My Clients", "Call List"],
             "supervisor": ["My Clients", "Call List", "All Clients", "Assign Clients", "CRM Report"],
             "manager": ["Call List", "All Clients", "Assign Clients", "CRM Report"],
             "owner": ["My Clients", "Call List", "All Clients", "Assign Clients", "CRM Report"]}


def sections_for(role):
    """The sections a role can open, and the pages in each."""
    out = {"Home": ["Home", "My Payslips", "My Account"] + (["Users"] if role == "owner" else []),
           "Attendance": ATT_PAGES[role]}
    for name, pages in (("Branch KPI", KPI_PAGES), ("HR", HR_PAGES), ("Payroll", PAY_PAGES), ("CRM", CRM_PAGES)):
        if pages.get(role):
            out[name] = pages[role]
    return out


def go_to(section, page=None):
    """Open a section, on its first page unless a page is given."""
    st.session_state["dest"] = section
    st.session_state["nav"] = (section, page)
    # A new number rebuilds the drop-down menus, which closes the one that was open.
    st.session_state["nav_n"] = st.session_state.get("nav_n", 0) + 1


def xl_table(t, formats=None, status=None):
    """Show a table across the full width. Click a column header to sort. status: a column to show in colour."""
    rows = min(len(t), 20)
    styled = t.style.format(formats or {}, na_rep="")
    if status and status in t.columns:
        styled = styled.map(colour_status, subset=[status])
    st.dataframe(styled, use_container_width=True, hide_index=True, height=38 + 35 * max(rows, 1))


def fmt_table(df, cols, formats=None, status=None):
    xl_table(df[list(cols)].rename(columns=cols), formats, status)


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


def module_cards(prefix, secs=None, on_click=choose):
    """One card per module. secs=None (not signed in): every card opens the sign-in page.
    With secs, a module the person cannot open says so instead of showing a button."""
    rows = [MODULES[:3], MODULES[3:]]
    for r, row in enumerate(rows):
        cols = st.columns(3)
        for col, (name, text, _) in zip(cols, row):
            with col, card(f"mod_{_key(name)}_{prefix}"):
                st.subheader(name)
                st.write(text)
                if secs is None or name in secs:
                    st.button(f"Open {name}", key=f"{prefix}_open_{_key(name)}", type="primary",
                              on_click=on_click, args=(name,))
                else:
                    st.caption("Your account does not have access. Ask the owner if you need it.")


def landing_page():
    """The open main page. No sign-in here. Each card leads to the sign-in page; access is checked after it."""
    st.title(PORTAL_NAME)
    st.caption("Choose where to go. You sign in with your own username and password. "
               "Each person sees the modules their role allows.")
    module_cards("land")


def login_page():
    dest = st.session_state.get("dest", "Home")
    st.title(f"{dest}: sign in" if dest != "Home" else "Sign in")
    st.caption("One account works for every module.")
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
    df = fact()
    branches = branch_list()
    code = user["branch_code"]
    name = branches.set_index("branch_code")["branch"].get(code, code)
    mine = df[df["branch_code"] == code]
    as_of = k.latest_data_date(mine) if len(mine) else date.today()
    start, _ = k.month_bounds(as_of)
    d = k.daily_breakdown(df, start, as_of, code)
    mb = k.metric_breakdown(df, start, as_of, code)
    title_band(f"My Branch: {name}", f"Month to date {pd.Timestamp(start):%d %b} to {pd.Timestamp(as_of):%d %b %Y}")
    tiles([("Adjusted Value, MTD", f"{d['adjusted'].sum():,.1f}", code, BLUE),
           ("Days reported", f"{len(d)}", "This month", BLUE),
           ("Average per day", f"{d['adjusted'].mean():,.1f}" if len(d) else "n/a", "Adjusted Value", BLUE),
           ("Top metric", mb.iloc[0]["metric"] if len(mb) else "No data",
            f"{mb.iloc[0]['share']:.0%} of the total" if len(mb) else "", BLUE)])
    if not len(d):
        st.info("No entries yet for this month.")
        return
    g1, g2 = st.columns(2)
    with g1, panel("mb_daily", "Daily Adjusted Value"):
        vbar(d.assign(day=d["date"].dt.strftime("%d"))[["day", "adjusted"]], "day", "adjusted", "Day of month")
    with g2, panel("mb_metric", "Adjusted Value by Metric"):
        hbar(mb[["metric", "adjusted"]], "metric", "adjusted", "Metric")
    section_band("By metric, month to date")
    fmt_table(mb, {"metric": "Metric", "multiplier": "Multiplier", "metric_value": "Metric Value",
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
    title_band(f"My Cluster: {cluster}",
               f"{info['label']} to date, {info['start']:%d %b} to {info['end']:%d %b %Y} &nbsp;|&nbsp; "
               f"Program Rank is counted across all {info['branches']} branches")
    tiles([("My Adjusted Value, QTD", f"{mine['adjusted']:,.1f}" if pd.notna(mine["adjusted"]) else "No data",
            mine["branch"], BLUE),
           ("My program rank", f"{mine['rank']:.0f} of {info['ranked']}" if pd.notna(mine["rank"]) else "No data",
            "All branches", BLUE),
           ("My rank in the cluster", f"{mine['cluster_rank']:.0f} of {int(crow['reporting'])}"
            if pd.notna(mine["cluster_rank"]) else "No data", cluster, BLUE),
           ("Cluster rank", f"{crow['cluster_rank']:.0f} of {int(clusters['cluster_rank'].notna().sum())}"
            if pd.notna(crow["cluster_rank"]) else "No data", "Among clusters", BLUE)])
    have = view.dropna(subset=["rank"])
    if len(have):
        with panel("mc_bar", f"{cluster}: Adjusted Value by Branch, {info['label']} to date"):
            hbar(have[["branch", "adjusted"]], "branch", "adjusted", "Branch")
    section_band(f"{cluster} branches, {info['label']} to date")
    quarter_table(view, info, with_cluster=False)
    st.caption("You see the figures of the branches in your cluster only.")


def page_quarter_ranking(user):
    df = fact()
    branches = branch_list()
    c1, c2 = st.columns(2)
    as_of = c1.date_input("As of date", value=k.latest_data_date(df), max_value=date.today())
    table, info = k.quarter_ranking(df, as_of, branches)
    clusters = k.cluster_summary(table)
    pick = c2.selectbox("Cluster", ["All clusters"] + sorted(table["cluster"].dropna().unique()))
    title_band("Quarter Ranking",
               f"{info['label']} to date, {info['start']:%d %b} to {info['end']:%d %b %Y} &nbsp;|&nbsp; "
               f"previous figures are for the full {info['prev_label']}")
    top = table.dropna(subset=["rank"])
    topc = clusters.dropna(subset=["cluster_rank"])
    tiles([("Adjusted Value, QTD", f"{top['adjusted'].sum():,.1f}", "All branches", BLUE),
           ("Top branch", top.iloc[0]["branch"] if len(top) else "No data",
            f"{top.iloc[0]['adjusted']:,.1f}" if len(top) else "", BLUE),
           ("Top cluster", topc.iloc[0]["cluster"] if len(topc) else "No data",
            f"{topc.iloc[0]['adjusted']:,.1f}" if len(topc) else "", BLUE),
           ("Branches reporting", f"{info['ranked']} of {info['branches']}", "This quarter",
            GREEN if info["ranked"] == info["branches"] else AMBER)])
    view = table if pick == "All clusters" else k.cluster_view(table, pick)
    shown = view.dropna(subset=["rank"])
    if len(top):
        g1, g2 = st.columns([3, 2])
        with g1, panel("qr_branch", "Adjusted Value by Branch" if pick == "All clusters" else f"{pick}: by Branch"):
            if len(shown):
                hbar(shown[["branch", "adjusted"]], "branch", "adjusted", "Branch")
        with g2, panel("qr_cluster", "Share by Cluster"):
            donut(topc[["cluster", "adjusted"]], "cluster", "adjusted", "Cluster")
    section_band("Clusters")
    fmt_table(clusters, {"cluster_rank": "Rank", "cluster": "Cluster", "adjusted": "Adjusted Value, QTD",
                         "share": "Share of Program", "avg_per_branch": "Avg per Branch",
                         "reporting": "Branches Reporting", "top_branch": "Top Branch", "best_rank": "Best Program Rank"},
              {"Rank": "{:.0f}", "Adjusted Value, QTD": "{:,.1f}", "Share of Program": "{:.1%}",
               "Avg per Branch": "{:,.1f}", "Branches Reporting": "{:.0f}", "Best Program Rank": "{:.0f}"})
    section_band("Branches" if pick == "All clusters" else f"{pick} branches")
    quarter_table(view, info)
    st.download_button("Download quarter ranking as CSV", view.to_csv(index=False), "quarter_ranking.csv", "text/csv")


# ---------------------------------------------------------------- dashboard building blocks
BLUE, GREY, GREEN, AMBER, RED, NAVY = "#0F6CBD", "#9AA5B1", "#2E8B57", "#D9822B", "#C0392B", "#1F2A44"
CLUSTER_COLOURS = ["#0F6CBD", "#2E8B57", "#D9822B", "#7A5AA6", "#3AA6B9", "#9AA5B1"]


def title_band(title, subtitle, colour=None):
    """The page's title band, in the colour of the module that is open."""
    st.markdown(f'<div class="band" style="background:{colour or CUR["colour"]}"><div class="band-t">{title}</div>'
                f'<div class="band-s">{subtitle}</div></div>', unsafe_allow_html=True)


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


def hbar(data, cat, val, cat_title, val_title="Adjusted Value"):
    """Horizontal bars, highest first."""
    chart(data, {"mark": {"type": "bar", "color": BLUE, "cornerRadiusEnd": 2},
                 "encoding": {"y": {"field": cat, "type": "nominal", "sort": "-x", "title": None},
                              "x": {"field": val, "type": "quantitative", "title": val_title},
                              "tooltip": [{"field": cat, "title": cat_title},
                                          {"field": val, "title": val_title, "format": ",.1f"}]},
                 "height": {"step": 20}})


def vbar(data, cat, val, cat_title, val_title="Adjusted Value"):
    """Upright bars in the order given."""
    chart(data, {"mark": {"type": "bar", "color": BLUE},
                 "encoding": {"x": {"field": cat, "type": "ordinal", "sort": None, "title": cat_title,
                                    "axis": {"labelAngle": 0}},
                              "y": {"field": val, "type": "quantitative", "title": val_title},
                              "tooltip": [{"field": cat, "title": cat_title},
                                          {"field": val, "title": val_title, "format": ",.1f"}]},
                 "height": 280})


def donut(data, cat, val, cat_title, val_title="Adjusted Value", colours=None):
    chart(data, {"mark": {"type": "arc", "innerRadius": 70},
                 "encoding": {"theta": {"field": val, "type": "quantitative", "stack": True},
                              "color": {"field": cat, "type": "nominal", "scale": {"range": colours or CLUSTER_COLOURS},
                                        "legend": {"title": None, "orient": "bottom"}},
                              "order": {"field": val, "type": "quantitative", "sort": "descending"},
                              "tooltip": [{"field": cat, "title": cat_title},
                                          {"field": val, "title": val_title, "format": ",.1f"}]},
                 "height": 320})


def colour_status(value):
    good, warn, bad = (f"color: {c}; font-weight: 600" for c in (GREEN, AMBER, RED))
    return {"Submitted": good, "OK": good, "Partial": warn, "Partial days": warn, "Behind": warn,
            "Not submitted": bad, "No data": bad}.get(value, "")


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

    section_band("Ranking, month to date")
    fmt_table(table,
              {"rank": "Rank", "branch": "Branch", "cluster": "Cluster", "adjusted": "Adjusted Value",
               "prev_adjusted": "Previous Month", "change_pct": "Change %", "prev_rank": "Previous Rank",
               "rank_change": "Rank Change", "days_reported": "Days Reported"},
              {"Rank": "{:.0f}", "Adjusted Value": "{:,.1f}", "Previous Month": "{:,.1f}", "Change %": "{:+.1%}",
               "Previous Rank": "{:.0f}", "Rank Change": "{:+.0f}", "Days Reported": "{:.0f}"})

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


def page_kpi_dashboard(user):
    df = fact()
    branches = branch_list()
    latest = k.latest_data_date(df)
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("From", value=latest.replace(day=1))
    end = c2.date_input("To", value=latest)
    metric = c3.selectbox("Metric", ["All metrics"] + list(k.get_metrics(db)["metric"]))
    if start > end:
        st.error("From must be on or before To.")
        return
    title_band("KPI Dashboard", f"{start:%d %b %Y} to {end:%d %b %Y} &nbsp;|&nbsp; {metric}")
    d = df if metric == "All metrics" else df[df["metric"] == metric]
    r = k.ranking(d, start, end, branches)
    have = r.dropna(subset=["rank"])
    tiles([("Adjusted Value", f"{have['adjusted'].sum():,.1f}", metric, BLUE),
           ("Top branch", have.iloc[0]["branch"] if len(have) else "No data",
            f"{have.iloc[0]['adjusted']:,.1f}" if len(have) else "", GREEN),
           ("Lowest branch", have.iloc[-1]["branch"] if len(have) else "No data",
            f"{have.iloc[-1]['adjusted']:,.1f}" if len(have) else "", AMBER),
           ("Average per branch", f"{have['adjusted'].mean():,.1f}" if len(have) else "n/a",
            f"{len(have)} of {len(branches)} reporting", BLUE)])
    if len(have):
        daily = k.daily_breakdown(d, start, end)
        g1, g2 = st.columns([3, 2])
        with g1, panel("kd_branch", "Adjusted Value by Branch"):
            hbar(have[["branch", "adjusted"]], "branch", "adjusted", "Branch")
        with g2, panel("kd_daily", "Daily Adjusted Value"):
            vbar(daily.assign(day=daily["date"].dt.strftime("%d %b"))[["day", "adjusted"]], "day", "adjusted", "Date")
    section_band("Ranking for the period")
    fmt_table(r, {"rank": "Rank", "branch": "Branch", "cluster": "Cluster", "adjusted": "Adjusted Value",
                  "share": "Share of Company", "days_reported": "Days Reported", "avg_per_day": "Avg per Day",
                  "last_date": "Last Reported"},
              {"Rank": "{:.0f}", "Adjusted Value": "{:,.1f}", "Share of Company": "{:.1%}",
               "Days Reported": "{:.0f}", "Avg per Day": "{:,.1f}", "Last Reported": "{:%d %b %Y}"})
    st.download_button("Download ranking as CSV", r.to_csv(index=False), "ranking.csv", "text/csv")
    st.caption("Figures refresh within 2 minutes, and at once after you save or import.")


def page_drill_down(user):
    df = fact()
    branches = branch_list()
    latest = k.latest_data_date(df)
    c1, c2, c3 = st.columns(3)
    code = c1.selectbox("Branch", branches["branch_code"], format_func=branch_label(branches))
    start = c2.date_input("From", value=latest.replace(day=1), key="dd_from")
    end = c3.date_input("To", value=latest, key="dd_to")
    name = branches.set_index("branch_code")["branch"][code]
    title_band(f"Drill-down: {name}", f"{code} &nbsp;|&nbsp; {start:%d %b %Y} to {end:%d %b %Y}")
    d = k.daily_breakdown(df, start, end, code)
    if not len(d):
        st.info("No entries for this branch in the selected dates.")
        return
    mb = k.metric_breakdown(df, start, end, code)
    best = d.loc[d["adjusted"].idxmax()]
    tiles([("Adjusted Value", f"{d['adjusted'].sum():,.1f}", name, BLUE),
           ("Days reported", f"{len(d)}", "In the period", BLUE),
           ("Average per day", f"{d['adjusted'].mean():,.1f}", "Adjusted Value", BLUE),
           ("Best day", f"{best['date']:%d %b}", f"{best['adjusted']:,.1f}", GREEN),
           ("Top metric", mb.iloc[0]["metric"], f"{mb.iloc[0]['share']:.0%} of the total", BLUE)])
    g1, g2 = st.columns(2)
    with g1, panel("dd_daily", "Daily Adjusted Value"):
        vbar(d.assign(day=d["date"].dt.strftime("%d %b"))[["day", "adjusted"]], "day", "adjusted", "Date")
    with g2, panel("dd_metric", "Adjusted Value by Metric"):
        hbar(mb[["metric", "adjusted"]], "metric", "adjusted", "Metric")
    section_band("By metric")
    fmt_table(mb, {"metric": "Metric", "multiplier": "Multiplier", "metric_value": "Metric Value",
                   "adjusted": "Adjusted Value", "share": "Share"},
              {"Multiplier": "{:.1f}", "Metric Value": "{:,.0f}", "Adjusted Value": "{:,.1f}", "Share": "{:.1%}"})


STATUS_COLOURS = {"Submitted": GREEN, "OK": GREEN, "Partial": AMBER, "Partial days": AMBER, "Behind": AMBER,
                  "Not submitted": RED, "No data": RED}


def status_donut(counts, title):
    """counts: table with columns status and branches."""
    order = [x for x in STATUS_COLOURS if x in set(counts["status"])]
    chart(counts, {"mark": {"type": "arc", "innerRadius": 70},
                   "encoding": {"theta": {"field": "branches", "type": "quantitative", "stack": True},
                                "color": {"field": "status", "type": "nominal",
                                          "scale": {"domain": order, "range": [STATUS_COLOURS[x] for x in order]},
                                          "legend": {"title": None, "orient": "bottom"}},
                                "tooltip": [{"field": "status", "title": "Status"},
                                            {"field": "branches", "title": title}]},
                   "height": 300})


def page_submission_check(user):
    day = st.date_input("Check date", value=k.last_working_day(), max_value=date.today())
    s = k.submission_check(db, day)
    n = {x: int((s["status"] == x).sum()) for x in ("Submitted", "Partial", "Not submitted")}
    title_band("Submission Check", f"{day:%A %d %b %Y}")
    tiles([("Submitted", n["Submitted"], f"of {len(s)} branches", GREEN),
           ("Partial", n["Partial"], "Some metrics missing", AMBER),
           ("Not submitted", n["Not submitted"], "No entries for the day", RED),
           ("Metrics expected", int(s["expected"].iloc[0]) if len(s) else 0, "Per branch", BLUE)])
    g1, g2 = st.columns([2, 3])
    with g1, panel("sc_status", "Branches by Status"):
        status_donut(s.groupby("status", as_index=False).size().rename(columns={"size": "branches"}), "Branches")
    with g2, panel("sc_entered", "Metrics Entered by Branch"):
        hbar(s[["branch", "entered"]], "branch", "entered", "Branch", "Metrics entered")
    missing = n["Partial"] + n["Not submitted"]
    section_band(f"{missing} branch(es) to follow up" if missing else "All branches submitted", RED if missing else GREEN)
    fmt_table(s.sort_values(["status", "branch_code"]),
              {"branch_code": "Branch Code", "branch": "Branch", "entered": "Metrics Entered",
               "expected": "Expected", "status": "Status"}, status="Status")
    st.caption("A branch on holiday shows Not submitted. Confirm holidays before following up.")


def page_data_quality(user):
    q = k.data_quality(db)
    n = q["status"].value_counts()
    title_band("Data Quality", "First and last date, days reported and gaps for every branch")
    tiles([("OK", int(n.get("OK", 0)), "Up to date and complete", GREEN),
           ("Behind", int(n.get("Behind", 0)), "Last date is older than others", AMBER),
           ("Partial days", int(n.get("Partial days", 0)), "Some days are incomplete", AMBER),
           ("No data", int(n.get("No data", 0)), "No entries yet", RED)])
    g1, g2 = st.columns([2, 3])
    with g1, panel("dq_status", "Branches by Status"):
        status_donut(q.groupby("status", as_index=False).size().rename(columns={"size": "branches"}), "Branches")
    with g2, panel("dq_days", "Days Reported by Branch"):
        hbar(q[["branch", "days_reported"]], "branch", "days_reported", "Branch", "Days reported")
    section_band("All branches")
    fmt_table(q, {"branch_code": "Branch Code", "branch": "Branch", "first_date": "First Date",
                  "last_date": "Last Date", "days_reported": "Days Reported", "partial_days": "Partial Days",
                  "status": "Status"}, status="Status")


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
        role = c1.selectbox("Role", list(k.ROLES))
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

    st.subheader("Change a user's role or branch")
    st.caption("employee: Attendance, requests, payslips and own CRM clients. branch: also Daily Entry, My Branch "
               "and My Cluster. supervisor: a branch user who also approves requests and sees the branch's attendance "
               "and CRM. hr: employees, schedules, leave and approvals, no salary. payroll: pay runs and rates. "
               "manager: dashboards and reports for all branches. owner: everything.")
    with st.form("change_role"):
        r1, r2, r3 = st.columns(3)
        who = r1.selectbox("User to change", list(users["username"]))
        new_role = r2.selectbox("New role", list(k.ROLES), index=list(k.ROLES).index("branch"))
        new_code = r3.selectbox("New branch", ["(none)"] + list(branches["branch_code"]))
        change = st.form_submit_button("Change role")
    if change:
        try:
            if who == user["username"]:
                raise ValueError("You cannot change your own role.")
            k.set_role(db, who, new_role, None if new_code == "(none)" else new_code, by=user["username"])
            st.success(f"{who} is now {new_role}. They must sign in again.")
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
    portal_settings(user)


def portal_settings(user):
    """Owner settings for HR and payroll data, shown at the end of the Admin page."""
    st.subheader("HR and payroll data")
    if h.encryption_on():
        st.success("Salary and pay data are encrypted with the SALARY_KEY secret.")
    else:
        st.warning("SALARY_KEY is not set in the app secrets. Add it before loading real salaries, then reboot the app. "
                   "Keep a copy of the key somewhere safe: without it, encrypted pay data cannot be read.")
    bank = h.store_bank_details(db)
    with st.form("set_bank"):
        on = st.checkbox("Store bank details in the portal", value=bank, key="set_bank_on")
        grace = st.number_input("Grace minutes before a time in counts as late", min_value=0, max_value=60,
                                value=int(h.get_setting(db, "grace_minutes", "0")), key="set_grace")
        go = st.form_submit_button("Save settings")
    if go:
        h.set_setting(db, "store_bank_details", "1" if on else "0", user["username"])
        h.set_setting(db, "grace_minutes", int(grace), user["username"])
        st.success("Settings saved.")
    st.caption("Leave bank details off to keep account numbers out of the portal. Payroll then uses the payout list "
               "(employee ID, name, net pay) in the bank's own payroll service.")
    if bank and st.button("Turn off and delete all stored bank details", key="clear_bank"):
        n = h.clear_bank_details(db, user["username"])
        h.set_setting(db, "store_bank_details", "0", user["username"])
        st.success(f"Bank details removed from {n} records.")


def page_my_account(user):
    st.title("My Account")
    st.write(f"Username: **{user['username']}**  |  Name: {user['full_name']}  |  Role: {user['role']}"
             + (f"  |  Branch: {user['branch_code']}" if user["branch_code"] else ""))
    st.subheader("Change password")
    password_form(user, forced=False)


# ---------------------------------------------------------------- home and attendance
def page_home(user):
    st.title(PORTAL_NAME)
    state, rec = a.status(db, user["username"])
    st.write(f"Signed in as **{user['full_name']}**. " + {"in": "You are timed in.", "out": "You are not timed in.",
             "no_time_out": "An earlier time in was never closed."}[state])
    module_cards("home", sections_for(user["role"]), on_click=go_to)
    c3, c4 = st.columns(2)
    with c3:
        notifications_card(user)
    with c4, card("home_pay"):
        st.subheader("Payslips")
        ps = p.my_payslips(db, user["username"])
        st.write(f"Latest: {ps.iloc[0]['start_date']} to {ps.iloc[0]['end_date']}." if len(ps) else "No payslips yet.")
        st.button("Open My Payslips", key="home_payslip", type="primary", on_click=go_to, args=("Home", "My Payslips"))


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
    pick = scope_branch(user) or c2.selectbox("Branch", ["All branches"] + list(branches["branch_code"]))
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


# ---------------------------------------------------------------- shared helpers for the HR, payroll and CRM pages
def people(role_filter=None, branch=None, active=True):
    """Usernames and names for pickers."""
    u = k.list_users(db)
    if active:
        u = u[u["active"].astype(int) == 1]
    if role_filter:
        u = u[u["role"].isin(role_filter)]
    if branch:
        u = u[u["branch_code"] == branch]
    return u.reset_index(drop=True)


def person_label(users):
    names = users.set_index("username")["full_name"].to_dict()
    return lambda x: f"{names.get(x, x)} ({x})" if x else "(none)"


def scope_branch(user):
    """Supervisors and branch users see their own branch only. None = all branches."""
    return user["branch_code"] if user["role"] in ("supervisor", "branch", "employee") else None


def read_upload(up):
    if up is None:
        return None
    if up.name.lower().endswith(".xlsx"):
        return pd.read_excel(up, dtype=str)
    return pd.read_csv(up, dtype=str)


def show_problems(problems, what="row(s)"):
    if problems is not None and len(problems):
        st.warning(f"{len(problems)} {what} were skipped:")
        xl_table(problems)


def peso(v):
    return "" if v is None or pd.isna(v) else f"₱{v:,.2f}"


# ---------------------------------------------------------------- Home additions
def page_my_payslips(user):
    st.title("My Payslips")
    ps = p.my_payslips(db, user["username"])
    if ps.empty:
        st.info("No payslips yet. A payslip shows here once payroll finalizes a pay period.")
        return
    labels = {r["id"]: f"{r['start_date']} to {r['end_date']}" + (f" (paid {r['pay_date']})" if r["pay_date"] else "")
              for _, r in ps.iterrows()}
    pid = st.selectbox("Pay period", list(labels), format_func=lambda x: labels[x])
    line = p.final_lines(db, pid, user["username"])
    if line.empty:
        st.info("No payslip for this period.")
        return
    L = line.iloc[0]
    title_band("Payslip", labels[pid])
    tiles([("Gross pay", peso(L["gross"]), "Before deductions", BLUE),
           ("Deductions", peso(L["contributions"] + L["tax"]), "Contributions and tax", AMBER),
           ("Net pay", peso(L["net"]), "Take-home", GREEN)])
    earn = [("Basic pay", L["basic"]), ("Overtime", L["overtime_pay"]), ("Night differential", L["night_diff_pay"]),
            ("Rest day work", L["rest_day_pay"]), ("Holiday work", L["holiday_pay"])]
    earn += [(x["label"], x["amount"]) for x in (L["allowance_lines"] or [])]
    earn += [(x["label"], x["amount"]) for x in (L["bonus_lines"] or [])]
    earn += [(x["label"], x["amount"]) for x in (L["adjustment_lines"] or [])]
    ded = [("SSS", L["sss"]), ("PhilHealth", L["philhealth"]), ("Pag-IBIG", L["pagibig"]), ("Withholding tax", L["tax"])]
    c1, c2 = st.columns(2)
    with c1:
        section_band("Earnings")
        xl_table(pd.DataFrame([e for e in earn if e[1]], columns=["Item", "Amount"]), {"Amount": "₱{:,.2f}"})
    with c2:
        section_band("Deductions")
        xl_table(pd.DataFrame(ded, columns=["Item", "Amount"]), {"Amount": "₱{:,.2f}"})
    st.caption(f"Absences: {L['absences']} · Late and undertime: {L['late_undertime_min']:.0f} minutes · "
               f"Deducted for absences {peso(L['absence_deduction'])} and lateness {peso(L['late_deduction'])}.")


def notifications_card(user):
    c.due_reminders(db, user["username"])
    notes = c.my_notifications(db, user["username"])
    with card("home_notes"):
        st.subheader("Notifications")
        if notes.empty:
            st.write("Nothing new.")
            return
        for _, n in notes.iterrows():
            st.write(f"{n['message']}  \n{str(n['at'])[:16].replace('T', ' ')}")
        if st.button("Mark all as read", key="notes_read"):
            c.mark_read(db, user["username"])
            st.rerun()


# ---------------------------------------------------------------- Attendance: requests and approvals
def page_my_requests(user):
    st.title("My Requests")
    me = user["username"]
    today = a.local_today()
    t1, t2 = st.tabs(["Attendance correction or overtime", "Leave"])
    with t1:
        with st.form("att_req"):
            c1, c2 = st.columns(2)
            wd = c1.date_input("Date", value=today, max_value=today, key="req_date")
            kind = c2.selectbox("Request", list(h.REQUEST_KINDS))
            c3, c4, c5 = st.columns(3)
            ri = c3.text_input("Correct time in (HH:MM)", key="req_in")
            ro = c4.text_input("Correct time out (HH:MM)", key="req_out")
            ot = c5.number_input("Overtime hours", min_value=0.0, max_value=12.0, step=0.5, key="req_ot")
            why = st.text_input("Reason", key="req_reason")
            go = st.form_submit_button("Send request")
        if go:
            try:
                h.request_attendance(db, me, wd, kind, why, ri or None, ro or None, ot or None)
                st.success("Request sent to your supervisor.")
            except ValueError as err:
                st.error(str(err))
        r = h.list_att_requests(db, username=me)
        section_band("My attendance requests")
        if r.empty:
            st.write("No requests yet.")
        else:
            fmt_table(r, {"work_date": "Date", "kind": "Request", "req_in": "Time In", "req_out": "Time Out",
                          "ot_hours": "OT Hours", "reason": "Reason", "status": "Status", "reviewed_by": "Reviewed By",
                          "review_note": "Note"}, {"OT Hours": "{:.1f}"}, status="Status")
            pend = r[r["status"] == "Pending"]
            if len(pend):
                with st.form("att_cancel"):
                    rid = st.selectbox("Cancel a pending request", list(pend["id"]),
                                       format_func=lambda x: f"{pend.set_index('id').loc[x, 'work_date']} {pend.set_index('id').loc[x, 'kind']}")
                    cancel = st.form_submit_button("Cancel request")
                if cancel:
                    try:
                        h.cancel_request(db, "att_requests", rid, me)
                        st.success("Request cancelled.")
                    except ValueError as err:
                        st.error(str(err))
    with t2:
        bal = h.leave_balances(db, me, today.year)
        section_band(f"My leave balance, {today.year}")
        fmt_table(bal, {"name": "Leave", "entitled": "Entitled", "used": "Used", "remaining": "Remaining"},
                  {"Entitled": "{:g}", "Used": "{:g}", "Remaining": "{:g}"})
        types = h.leave_types(db)
        with st.form("leave_req"):
            c1, c2, c3 = st.columns(3)
            code = c1.selectbox("Leave type", list(types["code"]), format_func=lambda x: types.set_index("code").loc[x, "name"])
            d0 = c2.date_input("From", value=today, key="lv_from")
            d1 = c3.date_input("To", value=today, key="lv_to")
            half = st.checkbox("Half day (one date only)", key="lv_half")
            why = st.text_input("Reason (optional)", key="lv_reason")
            go = st.form_submit_button("Request leave")
        if go:
            try:
                h.request_leave(db, me, code, d0, d1, why, half)
                st.success("Leave request sent.")
            except ValueError as err:
                st.error(str(err))
        r = h.list_leave_requests(db, username=me)
        if len(r):
            section_band("My leave requests")
            fmt_table(r, {"leave_name": "Leave", "start_date": "From", "end_date": "To", "days": "Days",
                          "status": "Status", "reviewed_by": "Reviewed By", "review_note": "Note"},
                      {"Days": "{:g}"}, status="Status")
            pend = r[r["status"] == "Pending"]
            if len(pend):
                with st.form("lv_cancel"):
                    rid = st.selectbox("Cancel a pending leave request", list(pend["id"]),
                                       format_func=lambda x: f"{pend.set_index('id').loc[x, 'leave_name']} {pend.set_index('id').loc[x, 'start_date']}")
                    cancel = st.form_submit_button("Cancel leave request")
                if cancel:
                    try:
                        h.cancel_request(db, "leave_requests", rid, me)
                        st.success("Leave request cancelled.")
                    except ValueError as err:
                        st.error(str(err))


def page_approvals(user):
    st.title("Approvals")
    ar = h.list_att_requests(db, status="Pending", approver=user)
    lr = h.list_leave_requests(db, status="Pending", approver=user)
    tiles([("Attendance requests", len(ar), "Waiting for you", AMBER if len(ar) else GREEN),
           ("Leave requests", len(lr), "Waiting for you", AMBER if len(lr) else GREEN)])
    section_band("Attendance corrections and overtime")
    if ar.empty:
        st.write("Nothing to approve.")
    else:
        fmt_table(ar, {"full_name": "Name", "branch_code": "Branch", "work_date": "Date", "kind": "Request",
                       "req_in": "Time In", "req_out": "Time Out", "ot_hours": "OT Hours", "reason": "Reason"},
                  {"OT Hours": "{:.1f}"})
        lab = {r["id"]: f"{r['full_name']}, {r['work_date']}, {r['kind']}" for _, r in ar.iterrows()}
        with st.form("ap_att"):
            rid = st.selectbox("Request", list(lab), format_func=lambda x: lab[x])
            dec = st.radio("Decision", ["Approve", "Reject"], key="ap_att_dec")
            note = st.text_input("Note to the employee (optional)", key="ap_att_note")
            go = st.form_submit_button("Save decision")
        if go:
            try:
                h.review_att_request(db, rid, dec == "Approve", user, note)
                st.success(f"Request {dec.lower()}d.")
            except ValueError as err:
                st.error(str(err))
    section_band("Leave")
    if lr.empty:
        st.write("Nothing to approve.")
    else:
        fmt_table(lr, {"full_name": "Name", "branch_code": "Branch", "leave_name": "Leave", "start_date": "From",
                       "end_date": "To", "days": "Days", "reason": "Reason"}, {"Days": "{:g}"})
        lab = {r["id"]: f"{r['full_name']}, {r['leave_name']}, {r['start_date']}" for _, r in lr.iterrows()}
        with st.form("ap_lv"):
            rid = st.selectbox("Leave request", list(lab), format_func=lambda x: lab[x])
            dec = st.radio("Decision", ["Approve", "Reject"], key="ap_lv_dec")
            note = st.text_input("Note to the employee (optional)", key="ap_lv_note")
            go = st.form_submit_button("Save leave decision")
        if go:
            try:
                h.review_leave(db, rid, dec == "Approve", user, note)
                st.success(f"Leave {dec.lower()}d.")
            except ValueError as err:
                st.error(str(err))


def page_attendance_report(user):
    today = a.local_today()
    branches = branch_list()
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("From", value=today.replace(day=1), key="ar_from")
    end = c2.date_input("To", value=today, key="ar_to")
    own = scope_branch(user)
    pick = own or c3.selectbox("Branch", ["All branches"] + list(branches["branch_code"]), key="ar_branch")
    if start > end:
        st.error("From must be on or before To.")
        return
    users = people(branch=None if pick == "All branches" else pick)
    names = list(users["username"])
    title_band("Attendance Report", f"{start:%d %b %Y} to {end:%d %b %Y} &nbsp;|&nbsp; {pick}")
    sm = h.attendance_summary(db, start, end, names)
    ds = h.daily_status(db, start, end, names)
    tiles([("People", len(sm), "In this report", BLUE),
           ("Absences", int(sm["absences"].sum()), "Scheduled days not worked", RED if sm["absences"].sum() else GREEN),
           ("Late", int(sm["late_count"].sum()), f"{sm['late_min'].sum():,.0f} minutes in total", AMBER if sm["late_count"].sum() else GREEN),
           ("Leave days", f"{sm['leave_days'].sum():g}", "Approved", BLUE),
           ("Overtime", f"{sm['ot_hours'].sum():,.1f} h", "Approved", BLUE)])
    if len(ds):
        counts = ds.groupby("status", as_index=False).size().rename(columns={"size": "days"})
        g1, g2 = st.columns([2, 3])
        with g1, panel("ar_status", "Days by Status"):
            donut(counts, "status", "days", "Status", "Days", ["#2E8B57", "#D9822B", "#C0392B", "#0F6CBD", "#7A5AA6", "#9AA5B1", "#3AA6B9"])
        with g2, panel("ar_late", "Late Minutes by Person"):
            late = sm[sm["late_min"] > 0]
            if len(late):
                hbar(late[["full_name", "late_min"]], "full_name", "late_min", "Name", "Late minutes")
            else:
                st.write("No late arrivals in this period.")
    section_band("Summary by person")
    fmt_table(sm, {"full_name": "Name", "branch_code": "Branch", "days_present": "Days Present", "absences": "Absences",
                   "late_count": "Times Late", "late_min": "Late Min", "undertime_min": "Undertime Min",
                   "leave_days": "Leave Days", "ot_hours": "OT Hours", "night_hours": "Night Hours",
                   "worked_hours": "Hours Worked", "no_time_out": "No Time Out"},
              {"Late Min": "{:,.0f}", "Undertime Min": "{:,.0f}", "Leave Days": "{:g}", "OT Hours": "{:.1f}",
               "Night Hours": "{:.1f}", "Hours Worked": "{:,.1f}"})
    st.download_button("Download the summary as CSV", sm.to_csv(index=False), "attendance_summary.csv", "text/csv")
    if len(ds):
        section_band("Day by day")
        t = ds.merge(users[["username", "full_name"]], on="username", how="left")
        t["first_in"] = [_hm(v) for v in t["first_in"]]
        t["last_out"] = [_hm(v) for v in t["last_out"]]
        fmt_table(t, {"work_date": "Date", "full_name": "Name", "shift_start": "Shift Start", "shift_end": "Shift End",
                      "first_in": "Time In", "last_out": "Time Out", "late_min": "Late Min", "undertime_min": "Undertime Min",
                      "ot_hours": "OT Hours", "status": "Status"},
                  {"Late Min": "{:,.0f}", "Undertime Min": "{:,.0f}", "OT Hours": "{:.1f}"}, status="Status")
        st.download_button("Download day by day as CSV", t.to_csv(index=False), "attendance_daily.csv", "text/csv")


# ---------------------------------------------------------------- HR
EMP_TEMPLATE = "Employee ID,Full Name,Username,Branch,Position,Employment Status,Civil Status,Date Hired\n,Juan Cruz,juan.cruz,Branch01,Encoder,Regular,Married,2024-03-01\n"
SCHED_DATE_TEMPLATE = "Employee,Date,Start,End,Break Minutes,Rest Day\n2026-0001,2026-11-02,08:00,17:00,60,No\n2026-0001,2026-11-07,,,,Yes\n"
SCHED_WEEK_TEMPLATE = "Employee,Day,Start,End,Break Minutes,Rest Day,From,To\n2026-0001,Mon,08:00,17:00,60,No,2026-11-01,2026-11-30\n2026-0001,Sun,,,,Yes,2026-11-01,2026-11-30\n"


def page_employees(user):
    st.title("Employees")
    branches = branch_list()
    emps = h.list_employees(db)
    tiles([("Active employees", int((emps["active"] == 1).sum()), "On record", BLUE),
           ("Linked to an account", int(emps["username"].notna().sum()), "Can use Attendance", BLUE),
           ("Not linked", int(emps["username"].isna().sum()), "Need an account for attendance and payroll",
            AMBER if emps["username"].isna().sum() else GREEN)])
    section_band("Employee list")
    fmt_table(emps.assign(active=emps["active"].map({1: "Yes", 0: "No"})),
              {"emp_id": "Employee ID", "full_name": "Name", "username": "Username", "branch_code": "Branch",
               "position": "Position", "employment_status": "Status", "civil_status": "Civil Status",
               "date_hired": "Date Hired", "rate_type": "Rate Type", "active": "Active"})
    st.caption("Salary is not shown here. Payroll sets rates on the Rates and Allowances page.")
    users = people()
    st.subheader("Add or edit an employee")
    choice = st.selectbox("Employee", ["(new employee)"] + list(emps["emp_id"]), key="emp_pick",
                          format_func=lambda x: x if x == "(new employee)" else f"{x} {emps.set_index('emp_id').loc[x, 'full_name']}")
    cur = emps.set_index("emp_id").loc[choice] if choice != "(new employee)" else None
    def val(col, default=""):
        return default if cur is None or cur[col] is None or (not isinstance(cur[col], str) and pd.isna(cur[col])) else cur[col]
    with st.form("emp_form"):
        c1, c2, c3 = st.columns(3)
        eid = c1.text_input("Employee ID (blank = next number)", value="" if cur is None else choice, key="emp_id")
        name = c2.text_input("Full name", value=val("full_name"), key="emp_name")
        uopts = ["(none)"] + list(users["username"])
        uname = c3.selectbox("Portal account", uopts, index=uopts.index(val("username")) if val("username") in uopts else 0,
                             format_func=person_label(users), key="emp_user")
        c4, c5, c6 = st.columns(3)
        bopts = ["(none)"] + list(branches["branch_code"])
        br = c4.selectbox("Branch", bopts, index=bopts.index(val("branch_code")) if val("branch_code") in bopts else 0, key="emp_branch")
        pos = c5.text_input("Position", value=val("position"), key="emp_pos")
        hired = c6.text_input("Date hired (YYYY-MM-DD)", value=val("date_hired"), key="emp_hired")
        c7, c8 = st.columns(2)
        es = c7.selectbox("Employment status", list(h.EMPLOYMENT_STATUSES),
                          index=list(h.EMPLOYMENT_STATUSES).index(val("employment_status", "Probationary")), key="emp_es")
        cs = c8.selectbox("Civil status", list(h.CIVIL_STATUSES), index=list(h.CIVIL_STATUSES).index(val("civil_status", "Single")), key="emp_cs")
        save = st.form_submit_button("Save employee")
    if save:
        try:
            saved = h.save_employee(db, user["username"], emp_id=eid or None, full_name=name,
                                    username=None if uname == "(none)" else uname, branch_code=None if br == "(none)" else br,
                                    position=pos or None, employment_status=es, civil_status=cs, date_hired=hired or None,
                                    rate_type=val("rate_type", "monthly"))
            st.success(f"Employee {saved} saved.")
        except ValueError as err:
            st.error(str(err))
    st.caption("Civil status is kept for records and BIR forms. Under the TRAIN law it does not change the tax rate.")
    st.subheader("Add many employees from a file")
    st.download_button("Download the employee template", EMP_TEMPLATE, "employee_template.csv", "text/csv")
    up = st.file_uploader("Employee list (.csv or .xlsx)", type=["csv", "xlsx"], key="emp_up")
    if up is not None and st.button("Load employees", key="emp_load"):
        try:
            done, probs = h.bulk_employees(db, read_upload(up), user["username"])
            st.success(f"{len(done)} employee(s) saved.")
            show_problems(probs)
        except ValueError as err:
            st.error(str(err))
    if len(emps):
        with st.form("emp_active"):
            target = st.selectbox("Employee to activate or deactivate", list(emps["emp_id"]), key="emp_act_pick")
            act = st.radio("Set to", ["Inactive", "Active"], key="emp_act")
            go = st.form_submit_button("Apply")
        if go:
            h.set_employee_active(db, target, act == "Active", user["username"])
            st.success(f"{target} is now {act.lower()}.")


def page_schedules(user):
    st.title("Schedules")
    st.write("Upload one row per employee per day, or a weekly pattern with a From and To date. "
             "Employee can be the employee ID or the username. A new row for the same person and day replaces the old one.")
    c1, c2 = st.columns(2)
    c1.download_button("Template: one row per day", SCHED_DATE_TEMPLATE, "schedule_by_date.csv", "text/csv")
    c2.download_button("Template: weekly pattern", SCHED_WEEK_TEMPLATE, "schedule_weekly.csv", "text/csv")
    up = st.file_uploader("Schedule file (.csv or .xlsx)", type=["csv", "xlsx"], key="sch_up")
    if up is not None and st.button("Check and load schedule", key="sch_load"):
        try:
            rows, probs = h.read_schedule_table(db, read_upload(up))
            n = h.import_schedules(db, rows, user["username"]) if rows else 0
            st.success(f"{n} schedule day(s) saved.")
            show_problems(probs)
        except ValueError as err:
            st.error(str(err))
    users = people()
    st.subheader("Change one day")
    with st.form("sch_one"):
        c1, c2, c3, c4 = st.columns(4)
        who = c1.selectbox("Person", list(users["username"]), format_func=person_label(users), key="sch_who")
        day = c2.date_input("Date", value=a.local_today(), key="sch_day")
        s0 = c3.text_input("Start (HH:MM)", value="08:00", key="sch_s")
        s1 = c4.text_input("End (HH:MM)", value="17:00", key="sch_e")
        c5, c6 = st.columns(2)
        brk = c5.number_input("Break minutes", min_value=0, max_value=180, value=60, step=15, key="sch_brk")
        rest = c6.checkbox("Rest day", key="sch_rest")
        go = st.form_submit_button("Save day")
    if go:
        try:
            h.set_schedule(db, who, day, s0, s1, brk, rest, user["username"])
            st.success("Schedule saved.")
        except ValueError as err:
            st.error(str(err))
    today = a.local_today()
    c1, c2 = st.columns(2)
    v0 = c1.date_input("Show from", value=today, key="sch_v0")
    v1 = c2.date_input("Show to", value=today + pd.Timedelta(days=13), key="sch_v1")
    sc = h.get_schedules(db, v0, v1)
    section_band("Schedules")
    if sc.empty:
        st.write("No schedules in these dates.")
    else:
        sc = sc.merge(users[["username", "full_name", "branch_code"]], on="username", how="left")
        sc["rest_day"] = sc["rest_day"].map({1: "Yes", 0: ""})
        fmt_table(sc, {"work_date": "Date", "full_name": "Name", "branch_code": "Branch", "shift_start": "Start",
                       "shift_end": "End", "break_minutes": "Break Min", "rest_day": "Rest Day"})


def page_leave_setup(user):
    st.title("Leave and Holidays")
    t1, t2, t3 = st.tabs(["Leave types", "Balances", "Holidays"])
    with t1:
        lt = h.leave_types(db, active_only=False)
        fmt_table(lt.assign(paid=lt["paid"].map({1: "Yes", 0: "No"})),
                  {"code": "Code", "name": "Leave", "paid": "Paid", "days_per_year": "Days per Year"}, {"Days per Year": "{:g}"})
        st.caption("Service Incentive Leave (5 paid days after one year of service) is the leave the Labor Code requires. "
                   "Other leave days follow company policy and the special leave laws. HR should confirm the list.")
        with st.form("lt_form"):
            c1, c2, c3, c4 = st.columns(4)
            code = c1.text_input("Code", key="lt_code")
            name = c2.text_input("Name", key="lt_name")
            days = c3.number_input("Days per year", min_value=0.0, step=1.0, key="lt_days")
            paid = c4.checkbox("Paid", value=True, key="lt_paid")
            go = st.form_submit_button("Save leave type")
        if go:
            try:
                h.save_leave_type(db, code, name, paid, days, user["username"])
                st.success("Leave type saved.")
            except ValueError as err:
                st.error(str(err))
    with t2:
        users = people()
        types = h.leave_types(db)
        with st.form("bal_form"):
            c1, c2, c3, c4 = st.columns(4)
            who = c1.selectbox("Person", list(users["username"]), format_func=person_label(users), key="bal_who")
            yr = c2.number_input("Year", min_value=2020, max_value=2100, value=a.local_today().year, key="bal_year")
            code = c3.selectbox("Leave type", list(types["code"]), key="bal_code")
            ent = c4.number_input("Entitled days", min_value=0.0, step=0.5, key="bal_ent")
            go = st.form_submit_button("Set balance")
        if go:
            try:
                h.set_leave_balance(db, who, int(yr), code, ent, user["username"])
                st.success("Balance saved.")
            except ValueError as err:
                st.error(str(err))
        if len(users):
            pick = st.selectbox("Show balances for", list(users["username"]), format_func=person_label(users), key="bal_show")
            fmt_table(h.leave_balances(db, pick, a.local_today().year),
                      {"name": "Leave", "entitled": "Entitled", "used": "Used", "remaining": "Remaining"},
                      {"Entitled": "{:g}", "Used": "{:g}", "Remaining": "{:g}"})
    with t3:
        hol = h.get_holidays(db)
        if len(hol):
            fmt_table(hol, {"hdate": "Date", "name": "Holiday", "kind": "Kind"})
        else:
            st.write("No holidays yet. Add this year's regular holidays and special non-working days.")
        with st.form("hol_form"):
            c1, c2, c3 = st.columns(3)
            d = c1.date_input("Date", value=a.local_today(), key="hol_d")
            name = c2.text_input("Name", key="hol_n")
            kind = c3.selectbox("Kind", ["regular", "special"], key="hol_k")
            add = st.form_submit_button("Save holiday")
        if add:
            try:
                h.set_holiday(db, d, name, kind, user["username"])
                st.success("Holiday saved.")
            except ValueError as err:
                st.error(str(err))
        if len(hol):
            with st.form("hol_rm"):
                d = st.selectbox("Remove a holiday", list(hol["hdate"]), key="hol_rm_d")
                rm = st.form_submit_button("Remove")
            if rm:
                h.remove_holiday(db, d, user["username"])
                st.success("Holiday removed.")


# ---------------------------------------------------------------- Payroll
def page_pay_runs(user):
    st.title("Pay Runs")
    with st.form("pp_new"):
        c1, c2, c3, c4 = st.columns(4)
        d0 = c1.date_input("Period start", value=a.local_today().replace(day=1), key="pp_d0")
        d1 = c2.date_input("Period end", value=a.local_today().replace(day=15), key="pp_d1")
        pay = c3.date_input("Pay date", value=a.local_today().replace(day=15), key="pp_pay")
        freq = c4.selectbox("Frequency", ["semi-monthly", "monthly"], key="pp_freq")
        c5, c6 = st.columns(2)
        part = c5.selectbox("Part of the month (semi-monthly)", [1, 2], key="pp_part")
        bm = c6.text_input("Include bonuses for month (YYYY-MM, optional)", key="pp_bm")
        go = st.form_submit_button("Create pay period")
    if go:
        try:
            p.create_period(db, d0, d1, freq, pay, part, bm or None, user["username"])
            st.success("Pay period created as a draft.")
        except ValueError as err:
            st.error(str(err))
    pers = p.periods(db)
    if pers.empty:
        st.info("No pay periods yet.")
        return
    lab = {r["id"]: f"{r['start_date']} to {r['end_date']} ({r['status']})" for _, r in pers.iterrows()}
    pid = st.selectbox("Pay period", list(lab), format_func=lambda x: lab[x], key="pp_pick")
    per = p.get_period(db, pid)
    lines, probs = p.compute_period(db, pid)
    title_band("Pay Run", f"{per['start_date']} to {per['end_date']} &nbsp;|&nbsp; {per['frequency']} &nbsp;|&nbsp; {per['status']}")
    if lines.empty:
        st.info("No employees with an account and a rate yet.")
        show_problems(probs, "employee(s)")
        return
    tiles([("Employees", len(lines), "In this run", BLUE),
           ("Gross pay", peso(lines["gross"].sum()), "Total", BLUE),
           ("Deductions", peso((lines["contributions"] + lines["tax"]).sum()), "Contributions and tax", AMBER),
           ("Net pay", peso(lines["net"].sum()), "To pay out", GREEN)])
    show_problems(probs, "employee(s) without a rate")
    section_band("Pay lines")
    money = {c: "₱{:,.2f}" for c in ("Basic", "Premiums", "Allowances", "Bonus", "Adjustments", "Gross", "SSS",
                                     "PhilHealth", "Pag-IBIG", "Tax", "Net")}
    fmt_table(lines, {"emp_id": "Employee ID", "full_name": "Name", "branch_code": "Branch", "basic": "Basic",
                      "premiums": "Premiums", "allowances": "Allowances", "bonus": "Bonus", "adjustments": "Adjustments",
                      "gross": "Gross", "sss": "SSS", "philhealth": "PhilHealth", "pagibig": "Pag-IBIG", "tax": "Tax", "net": "Net",
                      "absences": "Absences", "late_undertime_min": "Late Min"}, dict(money, **{"Late Min": "{:,.0f}"}))
    flat = lines.drop(columns=["allowance_lines", "bonus_lines", "adjustment_lines"], errors="ignore")
    c1, c2 = st.columns(2)
    c1.download_button("Download the pay register (CSV)", flat.to_csv(index=False), "pay_register.csv", "text/csv")
    payout = lines[["emp_id", "full_name", "net"]].rename(columns={"emp_id": "Employee ID", "full_name": "Name", "net": "Net Pay"})
    c2.download_button("Download the payout list for the bank (CSV)", payout.to_csv(index=False), "payout_list.csv", "text/csv")
    st.caption("The payout list has the employee ID, name and net pay only. Match it in the bank's payroll service.")
    if per["status"] == "Draft":
        st.subheader("Adjustments")
        adj = p.adjustments(db, pid)
        if len(adj):
            fmt_table(adj, {"username": "Username", "label": "Label", "amount": "Amount", "taxable": "Taxable"}, {"Amount": "₱{:,.2f}"})
        with st.form("pp_adj"):
            c1, c2, c3, c4 = st.columns(4)
            who = c1.selectbox("Employee", list(lines["username"]), key="adj_who")
            label = c2.text_input("Label", key="adj_label")
            amt = c3.number_input("Amount (negative to deduct)", step=100.0, key="adj_amt")
            tax = c4.checkbox("Taxable", value=True, key="adj_tax")
            add = st.form_submit_button("Add adjustment")
        if add:
            try:
                p.add_adjustment(db, pid, who, label, amt, tax, user["username"])
                st.success("Adjustment added.")
            except ValueError as err:
                st.error(str(err))
        st.subheader("Finalize")
        st.write("Check the lines against the current payroll first. Once final, the run cannot change and payslips appear.")
        sure = st.checkbox("I have checked this run", key="pp_sure")
        if st.button("Finalize this pay run", key="pp_final", disabled=not sure):
            try:
                n = p.finalize_period(db, pid, user["username"])
                st.success(f"Pay run finalized with {n} payslips.")
            except ValueError as err:
                st.error(str(err))


def page_rates(user):
    st.title("Rates and Allowances")
    emps = h.list_employees(db, with_pay=True, active_only=True)
    bank_on = h.store_bank_details(db)
    cols = {"emp_id": "Employee ID", "full_name": "Name", "username": "Username", "branch_code": "Branch",
            "rate_type": "Rate Type", "rate": "Rate"}
    if bank_on:
        cols["bank"] = "Bank Details"
    fmt_table(emps, cols, {"Rate": "₱{:,.2f}"})
    if not h.encryption_on():
        st.warning("SALARY_KEY is not set in the app secrets, so rates are stored without encryption.")
    if len(emps):
        with st.form("rate_form"):
            c1, c2, c3 = st.columns(3)
            eid = c1.selectbox("Employee", list(emps["emp_id"]), key="rate_emp",
                               format_func=lambda x: f"{x} {emps.set_index('emp_id').loc[x, 'full_name']}")
            rt = c2.selectbox("Rate type", list(h.RATE_TYPES), key="rate_type")
            rate = c3.number_input("Rate (₱ per month or per day)", min_value=0.0, step=500.0, key="rate_amt")
            bank = st.text_input("Bank details", key="rate_bank") if bank_on else None
            go = st.form_submit_button("Save rate")
        if go:
            try:
                h.set_pay(db, eid, rt, rate, user["username"], bank)
                st.success("Rate saved.")
            except ValueError as err:
                st.error(str(err))
    st.download_button("Download the rate template", "Employee ID,Rate Type,Rate\n2026-0001,monthly,26100\n2026-0002,daily,800\n",
                       "rate_template.csv", "text/csv")
    up = st.file_uploader("Rates file (.csv or .xlsx)", type=["csv", "xlsx"], key="rate_up")
    if up is not None and st.button("Load rates", key="rate_load"):
        try:
            n, probs = h.bulk_rates(db, read_upload(up), user["username"])
            st.success(f"{n} rate(s) saved.")
            show_problems(probs)
        except ValueError as err:
            st.error(str(err))
    st.subheader("Allowances")
    at = p.allowance_types(db)
    fmt_table(at.assign(taxable=at["taxable"].map({1: "Yes", 0: "No (up to the ceiling)"})),
              {"code": "Code", "name": "Allowance", "taxable": "Taxable", "monthly_cap": "Tax-free Ceiling per Month"},
              {"Tax-free Ceiling per Month": "₱{:,.2f}"})
    st.caption("De minimis ceilings follow BIR RR 29-2025 (from 6 January 2026). The amount above a ceiling is taxed.")
    linked = emps[emps["username"].notna()]
    if len(linked):
        with st.form("allw_form"):
            c1, c2, c3 = st.columns(3)
            who = c1.selectbox("Employee", list(linked["username"]), key="allw_who")
            code = c2.selectbox("Allowance", list(at["code"]), format_func=lambda x: at.set_index("code").loc[x, "name"], key="allw_code")
            amt = c3.number_input("Amount per month (0 removes it)", min_value=0.0, step=100.0, key="allw_amt")
            go = st.form_submit_button("Save allowance")
        if go:
            try:
                p.set_allowance(db, who, code, amt, user["username"])
                st.success("Allowance saved.")
            except ValueError as err:
                st.error(str(err))
    ea = p.employee_allowances(db)
    if len(ea):
        fmt_table(ea, {"username": "Username", "name": "Allowance", "monthly_amount": "Per Month"}, {"Per Month": "₱{:,.2f}"})


def page_bonus_rules(user):
    st.title("Targets and Bonus Rules")
    branches = branch_list()
    metrics = ["ALL"] + list(k.get_metrics(db, active_only=True)["metric"])
    mlabel = lambda m: "Total Adjusted Value" if m == "ALL" else m
    t1, t2, t3 = st.tabs(["Targets", "Bonus rules", "Achievement"])
    with t1:
        with st.form("tg_form"):
            c1, c2, c3, c4 = st.columns(4)
            month = c1.text_input("Month (YYYY-MM)", value=a.local_today().strftime("%Y-%m"), key="tg_month")
            br = c2.selectbox("Branch", list(branches["branch_code"]), key="tg_branch")
            metric = c3.selectbox("Metric", metrics, format_func=mlabel, key="tg_metric")
            tg = c4.number_input("Target", min_value=0.0, step=10.0, key="tg_value")
            go = st.form_submit_button("Save target")
        if go:
            try:
                p.set_target(db, br, metric, month, tg, user["username"])
                st.success("Target saved.")
            except ValueError as err:
                st.error(str(err))
        t = p.get_targets(db)
        if len(t):
            fmt_table(t.assign(metric=t["metric"].map(mlabel)), {"month": "Month", "branch_code": "Branch",
                                                                 "metric": "Metric", "target": "Target"}, {"Target": "{:,.1f}"})
    with t2:
        st.write("For each metric, the highest level a branch reaches decides the bonus for every employee of that branch.")
        with st.form("br_form"):
            c1, c2, c3, c4 = st.columns(4)
            metric = c1.selectbox("Metric", metrics, format_func=mlabel, key="br_metric")
            pct = c2.number_input("At or above % of target", min_value=1.0, value=100.0, step=5.0, key="br_pct")
            kind = c3.selectbox("Bonus type", ["fixed", "pct_basic"],
                                format_func=lambda x: "Fixed amount" if x == "fixed" else "% of basic pay", key="br_kind")
            val = c4.number_input("Amount or %", min_value=0.0, step=100.0, key="br_val")
            go = st.form_submit_button("Add rule")
        if go:
            try:
                p.add_bonus_rule(db, metric, pct, kind, val, user["username"])
                st.success("Rule added.")
            except ValueError as err:
                st.error(str(err))
        r = p.bonus_rules(db)
        if len(r):
            fmt_table(r.assign(metric=r["metric"].map(mlabel), kind=r["kind"].map({"fixed": "Fixed", "pct_basic": "% of basic"})),
                      {"metric": "Metric", "min_pct": "From % of Target", "kind": "Type", "value": "Value"},
                      {"From % of Target": "{:.0f}%", "Value": "{:,.2f}"})
            with st.form("br_rm"):
                rid = st.selectbox("Remove a rule", list(r["id"]), key="br_rm_id",
                                   format_func=lambda x: f"{mlabel(r.set_index('id').loc[x, 'metric'])} from {r.set_index('id').loc[x, 'min_pct']:.0f}%")
                rm = st.form_submit_button("Remove rule")
            if rm:
                p.remove_bonus_rule(db, rid, user["username"])
                st.success("Rule removed.")
    with t3:
        month = st.text_input("Month (YYYY-MM)", value=a.local_today().strftime("%Y-%m"), key="ach_month")
        try:
            ach = p.achievement(db, month, fact())
        except ValueError as err:
            st.error(str(err))
            return
        if ach.empty:
            st.info("No targets for this month yet.")
        else:
            fmt_table(ach.assign(metric=ach["metric"].map(mlabel)),
                      {"branch_code": "Branch", "metric": "Metric", "target": "Target", "actual": "Actual", "pct": "% of Target"},
                      {"Target": "{:,.1f}", "Actual": "{:,.1f}", "% of Target": "{:.0f}%"})


def page_thirteenth(user):
    st.title("13th Month Pay")
    yr = st.number_input("Year", min_value=2020, max_value=2100, value=a.local_today().year, key="tm_year")
    t = p.thirteenth_month(db, int(yr))
    if t.empty:
        st.info("No final pay runs this year yet.")
        return
    fmt_table(t, {"full_name": "Name", "username": "Username", "basic_year": "Basic Pay This Year", "thirteenth_month": "13th Month"},
              {"Basic Pay This Year": "₱{:,.2f}", "13th Month": "₱{:,.2f}"})
    st.caption("Basic pay in final pay runs of the year divided by 12. It must be paid by 24 December. "
               "Up to ₱90,000 of 13th month and other benefits is tax free.")
    st.download_button("Download as CSV", t.to_csv(index=False), "thirteenth_month.csv", "text/csv")


PAY_LABELS = {"days_per_year": "Working days per year (monthly to daily rate)", "hours_per_day": "Hours per day",
              "days_per_month_daily": "Days per month for daily-paid contributions", "ot_rate": "Overtime rate",
              "rest_day_rate": "Rest day rate", "regular_holiday_premium": "Regular holiday premium (extra)",
              "special_day_premium": "Special day premium (extra)", "night_diff": "Night differential (extra)",
              "sss_rate_ee": "SSS employee rate", "sss_msc_min": "SSS lowest salary credit", "sss_msc_max": "SSS highest salary credit",
              "phic_rate_ee": "PhilHealth employee rate", "phic_floor": "PhilHealth salary floor",
              "phic_ceiling": "PhilHealth salary ceiling", "hdmf_rate_ee": "Pag-IBIG employee rate",
              "hdmf_max_salary": "Pag-IBIG highest fund salary"}


def page_pay_settings(user):
    st.title("Pay Settings")
    st.warning("These values decide every payslip. The payroll lead must confirm them before go-live and after any change in the law.")
    s = p.pay_settings(db)
    with st.form("ps_form"):
        vals = {}
        cols = st.columns(2)
        for i, (key, label) in enumerate(PAY_LABELS.items()):
            vals[key] = cols[i % 2].number_input(label, value=float(s[key]), key="ps_" + key, format="%.4f")
        vals["contrib_split"] = st.selectbox("Semi-monthly contributions", ["split", "second"], key="ps_split",
                                             index=["split", "second"].index(s["contrib_split"]),
                                             format_func=lambda x: "Half each period" if x == "split" else "All in the second period")
        go = st.form_submit_button("Save settings")
    if go:
        try:
            p.save_pay_settings(db, vals, user["username"])
            st.success("Settings saved.")
        except ValueError as err:
            st.error(str(err))
    st.subheader("Withholding tax tables")
    for freq, rows in p.TAX_TABLES.items():
        st.write(f"**{freq.title()}**")
        xl_table(pd.DataFrame(rows, columns=["Over (₱)", "Fixed Tax (₱)", "Rate on Excess"]),
                 {"Over (₱)": "{:,.0f}", "Fixed Tax (₱)": "{:,.2f}", "Rate on Excess": "{:.0%}"})
    st.caption("Sources: " + "; ".join(p.PAY_SOURCES) + ".")


# ---------------------------------------------------------------- CRM
CLIENT_TEMPLATE = "Name,Company,Phone,Email,Branch,Source,Notes\nRosa Diaz,Diaz Trading,0917 123 4567,rosa@example.com,Branch01,Walk-in,\n"


def contact_form(user, options, key):
    """Log a contact for one of the given clients (a table with id and name)."""
    if options.empty:
        return
    users = people(branch=scope_branch(user))
    lab = {r["id"]: f"{r['name']} ({r['status']})" for _, r in options.iterrows()}
    with st.form(key):
        c1, c2 = st.columns(2)
        cid = c1.selectbox("Client", list(lab), format_func=lambda x: lab[x], key=key + "_cid")
        outcome = c2.selectbox("Outcome", [s for s in c.STATUSES if s != "New"], key=key + "_out")
        note = st.text_input("Note", key=key + "_note")
        c3, c4, c5 = st.columns(3)
        again = c3.checkbox("Call again", key=key + "_again")
        when = c4.date_input("On", value=a.local_today() + pd.Timedelta(days=3), key=key + "_when")
        uopts = list(users["username"]) or [user["username"]]
        who = c5.selectbox("Who will call", uopts, index=uopts.index(user["username"]) if user["username"] in uopts else 0,
                           format_func=person_label(users), key=key + "_who")
        go = st.form_submit_button("Save contact")
    if go:
        try:
            warns = c.log_contact(db, cid, user["username"], outcome, note, when if again else None, who if again else None)
            st.success("Contact saved.")
            for w in warns:
                st.warning(w)
        except ValueError as err:
            st.error(str(err))
    hist = c.contacts(db, cid=st.session_state.get(key + "_cid") or list(lab)[0])
    if len(hist):
        st.caption("History of this client")
        fmt_table(hist, {"at": "When", "username": "By", "outcome": "Outcome", "note": "Note"})


def page_my_clients(user):
    st.title("My Clients")
    me = user["username"]
    mine = c.clients(db, assigned_to=me)
    due = c.call_list(db, me, "Pending", a.local_today())
    tiles([("My clients", len(mine), "Assigned to me", BLUE),
           ("Open", int((~mine["status"].isin(c.CLOSED)).sum()) if len(mine) else 0, "Not closed", BLUE),
           ("Call-backs due", len(due), "Today or overdue", AMBER if len(due) else GREEN),
           ("Closed won", int((mine["status"] == "Closed won").sum()) if len(mine) else 0, "All time", GREEN)])
    with st.form("cl_add"):
        st.subheader("Add a client")
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name", key="cl_name")
        comp = c2.text_input("Company", key="cl_comp")
        src = c3.text_input("Source (walk-in, referral, ad)", key="cl_src")
        c4, c5 = st.columns(2)
        phone = c4.text_input("Phone", key="cl_phone")
        email = c5.text_input("Email", key="cl_email")
        notes = st.text_input("Notes", key="cl_notes")
        go = st.form_submit_button("Add client")
    if go:
        try:
            c.add_client(db, me, name, comp, phone, email, user["branch_code"], src, notes, assigned_to=me)
            st.success("Client added and assigned to you.")
        except ValueError as err:
            st.error(str(err))
    status = st.selectbox("Show", ["Open", "All"] + list(c.STATUSES), key="cl_filter")
    view = mine if status == "All" else (mine[~mine["status"].isin(c.CLOSED)] if status == "Open" else mine[mine["status"] == status])
    section_band("My clients")
    if view.empty:
        st.write("No clients here.")
    else:
        fmt_table(view, {"name": "Name", "company": "Company", "phone": "Phone", "email": "Email", "status": "Status",
                         "last_contact_at": "Last Contact", "last_contact_by": "By", "next_call_on": "Call Again On"})
        st.subheader("Log a contact")
        contact_form(user, view, "mc_contact")


def page_call_list(user):
    st.title("Call List")
    br = scope_branch(user) if user["role"] in ("supervisor", "branch", "employee") else None
    sees_all = user["role"] in ("supervisor", "manager", "owner")
    who = None if sees_all and st.checkbox("Show everyone's call-backs", key="call_all") else user["username"]
    calls = c.call_list(db, who, "Pending", branch_code=br if who is None else None)
    today = str(a.local_today())
    due = calls[calls["call_on"] <= today] if len(calls) else calls
    tiles([("Pending call-backs", len(calls), "In this list", BLUE),
           ("Due", len(due), "Today or overdue", AMBER if len(due) else GREEN)])
    section_band("Who calls which client, when")
    if calls.empty:
        st.write("No pending call-backs.")
        return
    calls = calls.assign(when=["Overdue" if d < today else ("Today" if d == today else "Later") for d in calls["call_on"]])
    fmt_table(calls, {"call_on": "Call On", "when": "When", "client": "Client", "company": "Company", "phone": "Phone",
                      "assigned_name": "Caller", "client_status": "Client Status", "created_by": "Set By"})
    mine = calls[calls["assigned_to"] == user["username"]]
    if len(mine):
        st.subheader("Log a call")
        contact_form(user, c.clients(db)[lambda d: d["id"].isin(mine["client_id"])], "cl_contact")
    if sees_all:
        users = people(branch=br)
        with st.form("call_re"):
            c1, c2 = st.columns(2)
            cid = c1.selectbox("Call-back", list(calls["id"]), key="re_call",
                               format_func=lambda x: f"{calls.set_index('id').loc[x, 'client']} on {calls.set_index('id').loc[x, 'call_on']}")
            to = c2.selectbox("Give to", list(users["username"]), format_func=person_label(users), key="re_to")
            go = st.form_submit_button("Reassign")
        if go:
            try:
                c.reassign_call(db, cid, to, user["username"])
                st.success("Call-back reassigned.")
            except ValueError as err:
                st.error(str(err))


def page_all_clients(user):
    st.title("All Clients")
    br = scope_branch(user)
    branches = branch_list()
    c1, c2, c3 = st.columns(3)
    pick = br or c1.selectbox("Branch", ["All branches"] + list(branches["branch_code"]), key="ac_branch")
    status = c2.selectbox("Status", ["All"] + list(c.STATUSES), key="ac_status")
    search = c3.text_input("Search name, company, phone or email", key="ac_search")
    df = c.clients(db, branch_code=None if pick == "All branches" else pick, status=None if status == "All" else status, search=search)
    counts = df.groupby("status", as_index=False).size().rename(columns={"size": "clients"}) if len(df) else None
    tiles([("Clients", len(df), "In this view", BLUE),
           ("Untouched", int(((df["status"] == "New") & df["last_contact_at"].isna()).sum()) if len(df) else 0, "Never contacted", AMBER),
           ("Closed won", int((df["status"] == "Closed won").sum()) if len(df) else 0, "In this view", GREEN)])
    if counts is not None:
        with panel("ac_status", "Clients by Status"):
            hbar(counts, "status", "clients", "Status", "Clients")
    section_band("Clients")
    if len(df):
        fmt_table(df, {"name": "Name", "company": "Company", "phone": "Phone", "email": "Email", "branch_code": "Branch",
                       "status": "Status", "assigned_name": "Assigned To", "last_contact_at": "Last Contact",
                       "next_call_on": "Call Again On", "source": "Source"})
        st.download_button("Download as CSV", df.to_csv(index=False), "clients.csv", "text/csv")
    st.subheader("Upload clients")
    st.download_button("Download the client template", CLIENT_TEMPLATE, "client_template.csv", "text/csv")
    up = st.file_uploader("Client list (.csv or .xlsx)", type=["csv", "xlsx"], key="ac_up")
    if up is not None and st.button("Load clients", key="ac_load"):
        try:
            n, skipped = c.bulk_clients(db, read_upload(up), user["username"], default_branch=br)
            st.success(f"{n} client(s) added. Duplicates are skipped.")
            show_problems(skipped)
        except ValueError as err:
            st.error(str(err))


def page_assign_clients(user):
    st.title("Assign Clients")
    br = scope_branch(user)
    branches = branch_list()
    pick = br or st.selectbox("Branch", ["All branches"] + list(branches["branch_code"]), key="as_branch")
    branch = None if pick == "All branches" else pick
    inc = st.checkbox("Include untouched clients already assigned (reshuffle them)", key="as_inc")
    pool = c.untouched(db, branch, inc)
    tiles([("Untouched clients", len(pool), "New, never contacted", AMBER if len(pool) else GREEN)])
    users = people(role_filter=["employee", "branch", "supervisor"], branch=branch)
    if users.empty:
        st.info("No employees in this branch to assign to.")
        return
    chosen = st.multiselect("Share them out among", list(users["username"]), format_func=person_label(users), key="as_people")
    if st.button("Assign at random", key="as_go", type="primary", disabled=not chosen or pool.empty):
        try:
            counts = c.assign_random(db, chosen, user["username"], branch_code=branch, include_assigned=inc)
            st.success("Assigned: " + ", ".join(f"{u} {n}" for u, n in counts.items()))
        except ValueError as err:
            st.error(str(err))
    st.caption("Clients are shuffled and dealt out in turn, so everyone gets the same number, give or take one. "
               "Each person gets a notification.")


def page_crm_report(user):
    today = a.local_today()
    br = scope_branch(user)
    c1, c2 = st.columns(2)
    start = c1.date_input("From", value=today.replace(day=1), key="cr_from")
    end = c2.date_input("To", value=today, key="cr_to")
    title_band("CRM Report", f"{start:%d %b %Y} to {end:%d %b %Y}" + (f" &nbsp;|&nbsp; {br}" if br else ""))
    con = c.contacts(db, start=start, end=end)
    if br:
        con = con[con["branch_code"] == br]
    won = con[con["outcome"] == "Closed won"]
    tiles([("Contacts", len(con), "In the period", BLUE), ("Clients reached", con["client_id"].nunique() if len(con) else 0, "Different clients", BLUE),
           ("Closed won", len(won), "In the period", GREEN), ("People active", con["username"].nunique() if len(con) else 0, "Made a contact", BLUE)])
    if len(con):
        g1, g2 = st.columns(2)
        with g1, panel("cr_people", "Contacts by Person"):
            hbar(con.groupby("username", as_index=False).size().rename(columns={"size": "contacts"}), "username", "contacts", "Person", "Contacts")
        with g2, panel("cr_branch", "Contacts by Branch"):
            hbar(con.groupby("branch_code", as_index=False).size().rename(columns={"size": "contacts"}), "branch_code", "contacts", "Branch", "Contacts")
    link = c.kpi_link(db)
    section_band("Link to Branch KPI")
    if user["role"] == "owner":
        metrics = ["(not linked)"] + list(k.get_metrics(db, active_only=True)["metric"])
        with st.form("cr_link"):
            c1, c2, c3 = st.columns(3)
            m = c1.selectbox("Branch KPI metric", metrics, index=metrics.index(link["metric"]) if link["metric"] in metrics else 0, key="cr_metric")
            cnt = c2.selectbox("Count", ["contacts", "closed_won"], index=["contacts", "closed_won"].index(link["count"]),
                               format_func=lambda x: "Every contact" if x == "contacts" else "Closed won only", key="cr_count")
            mode = c3.selectbox("Use", ["validate", "fill"], index=["validate", "fill"].index(link["mode"]),
                                format_func=lambda x: "Check what branches type" if x == "validate" else "Fill the entries", key="cr_mode")
            go = st.form_submit_button("Save link")
        if go:
            try:
                c.set_kpi_link(db, None if m == "(not linked)" else m, cnt, mode, user["username"])
                st.success("Link saved.")
                link = c.kpi_link(db)
            except ValueError as err:
                st.error(str(err))
    if not link["metric"]:
        st.write("No Branch KPI metric is linked yet." + (" The owner sets the link here." if user["role"] != "owner" else ""))
        return
    st.write(f"Linked metric: **{link['metric']}**, counting {'every contact' if link['count'] == 'contacts' else 'closed won only'}.")
    if link["mode"] == "validate":
        v = c.validation(db, start, end)
        if br:
            v = v[v["branch_code"] == br]
        fmt_table(v, {"date": "Date", "branch_code": "Branch", "value": "Entered in Branch KPI", "crm_count": "CRM Count",
                      "difference": "Difference", "check": "Check"}, {"Entered in Branch KPI": "{:,.0f}", "Difference": "{:+,.0f}"})
    elif user["role"] in ("owner", "manager"):
        over = st.checkbox("Overwrite values branches already typed", key="cr_over")
        if st.button("Fill Branch KPI from the CRM for these dates", key="cr_fill"):
            n = c.fill_kpi(db, start, end, user["username"], over)
            refresh_data()
            st.success(f"{n} entries written to {link['metric']}.")
    month = st.text_input("Branch achievement for month (YYYY-MM)", value=today.strftime("%Y-%m"), key="cr_month")
    try:
        ba = c.branch_achievement(db, month)
        if br:
            ba = ba[ba["branch_code"] == br]
        fmt_table(ba, {"rank": "Rank", "branch": "Branch", "crm_count": "CRM Count", "target": "Target", "pct": "% of Target"},
                  {"Target": "{:,.0f}", "% of Target": "{:.0f}%"})
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
    "My Payslips": page_my_payslips, "My Requests": page_my_requests, "Approvals": page_approvals,
    "Employees": page_employees, "Schedules": page_schedules, "Leave and Holidays": page_leave_setup,
    "Pay Runs": page_pay_runs, "Rates and Allowances": page_rates, "Targets and Bonus Rules": page_bonus_rules,
    "13th Month": page_thirteenth, "Pay Settings": page_pay_settings,
    "My Clients": page_my_clients, "Call List": page_call_list, "All Clients": page_all_clients,
    "Assign Clients": page_assign_clients, "CRM Report": page_crm_report,
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
    asked = (st.session_state.get("nav") or (st.session_state.get("dest"),))[0]
    denied = asked if asked not in (None, "Home", *secs) else None
    if denied:
        st.session_state.pop("dest", None)
        st.session_state.pop("nav", None)
    # The open page is kept in the address too, so a refresh returns to the same page.
    section, page = st.session_state.get("nav") or (
        st.query_params.get("sec") or st.session_state.get("dest"), st.query_params.get("pg"))
    if section not in secs:
        section = "Home"
    if page not in secs[section]:
        page = secs[section][0]
    st.session_state["nav"] = (section, page)
    CUR["colour"] = MOD_COLOUR.get(section, "#1F2A44")
    if st.query_params.get("pg") != page or st.query_params.get("sec") != section:
        st.query_params["sec"] = section
        st.query_params["pg"] = page
    with st.container(key="menu_card"):
        menus = [m[0] for m in MODULES if m[0] in secs]
        nn = st.session_state.get("nav_n", 0)
        cols = st.columns([2.2, 0.7] + [1.15] * len(menus) + [max(0.3, 6.0 - 1.15 * len(menus)), 1.8],
                          vertical_alignment="center")
        cols[0].markdown(f'<div class="brand"><span class="dot"></span>{PORTAL_NAME}</div>', unsafe_allow_html=True)
        with cols[1].container(key="navsec_Home"):
            st.button("Home", key="nav_home", type="tertiary", on_click=go_to, args=("Home", "Home"))
        for i, name in enumerate(menus):
            with cols[2 + i].container(key=f"navsec_{name.replace(' ', '_')}_{nn}"):
                with st.popover(name):
                    for p in secs[name]:
                        st.button(p, key=f"nav_{name}_{p}", type="tertiary", on_click=go_to, args=(name, p))
        with cols[-1].container(key=f"navsec_user_{nn}"):
            with st.popover(user["full_name"]):
                st.caption(f"Role: {user['role']}")
                for p in secs["Home"][1:]:
                    st.button(p, key=f"nav_Home_{p}", type="tertiary", on_click=go_to, args=("Home", p))
                out = st.button("Sign out", key="nav_sign_out")
    # the open section is underlined in the bar; the breadcrumb sits in its own strip below
    trail = ["Home"] if section == "Home" and page == "Home" else (
        ["Home", page] if section == "Home" else ["Home", section, page])
    st.markdown(
        f'<style>div[class*="st-key-navsec_{section.replace(" ", "_")}"] button {{'
        f'border-bottom: 3px solid {MOD_COLOUR.get(section, "#5BB0F0") if section != "Home" else "#5BB0F0"} !important; '
        'border-radius: 0 !important; background: rgba(255,255,255,.10) !important;}</style>'
        f'<style>.crumb {{border-left: 6px solid {CUR["colour"]};}}</style>'
        '<div class="crumb">' + '<i>/</i>'.join(
            f"<b>{t}</b>" if i == len(trail) - 1 else f"<span>{t}</span>" for i, t in enumerate(trail)) + "</div>",
        unsafe_allow_html=True)
    if True:
        if out:
            k.end_session(db, st.session_state.get("token"))
            st.session_state.pop("user", None)
            st.session_state.pop("token", None)
            st.session_state.pop("dest", None)
            st.session_state.pop("nav", None)
            st.query_params.clear()
            st.rerun()
    if denied:
        st.warning(f"Your account does not have {denied} access. Ask the owner if you need it.")
    PAGE_FUNCS[page](user)
    st.caption(f"You stay signed in for {k.SESSION_HOURS} hours, or until you sign out. "
               "Do not share the page address while signed in.")


main()
