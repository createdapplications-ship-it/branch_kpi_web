# Company Portal

One app, one database, one account per person. Sections: Home, Attendance, Branch KPI, HR, Payroll and CRM.
Each person sees only the sections their role allows.

## Sign-in, Home and menu
- The first page is the sign-in page. Nothing else shows before sign-in.
- After sign-in, Home shows a card only for the modules the person can open. The menu bar shows the same modules.
- The menu bar stays on one line. On a phone it scrolls sideways.
- Each module has its own colour: Attendance teal, Branch KPI blue, HR purple, Payroll green, CRM brown. The colour shows on the card, the menu mark, the title band and the breadcrumb.
- Colours and card text are in the MODULES list at the top of app.py.

## Module access (owner)
- Users page, section Module access. The table shows every active user and their access in each module.
- For one user and one module, pick: Role default, No access, or a level (for example Attendance: Supervisor, or HR: HR staff).
- A level gives the pages and rights of that role inside that module only. Example: an employee with Attendance set to Supervisor can approve requests for their branch, and nothing else changes.
- Branch levels (Branch entry, Supervisor) need the user to have a branch.
- An owner always has full access. You cannot change your own access.
- Changes apply on the user's next click. No new sign-in is needed. Every change is in the activity log.
- Reset access puts one user back to what their role gives.

## Roles

| Role | What they can do |
|---|---|
| employee | Time in and out, requests (corrections, overtime, leave), own payslips, own CRM clients |
| branch | Employee, plus Branch KPI daily entry, My Branch and My Cluster |
| supervisor | Branch, plus approving the branch's requests, branch attendance, branch CRM and random assignment |
| hr | Employees, schedules, leave and holidays, approvals, attendance reports. No salary |
| payroll | Pay runs, rates and allowances, targets and bonus rules, 13th month, pay settings |
| manager | Dashboards and reports for all branches, approvals, CRM for all branches |
| owner | Everything, including Users and Admin |

## New secrets

- `SALARY_KEY`: any long random text. It encrypts salaries, bank details (if stored) and final pay lines.
  Set it before loading real salaries. Keep a copy somewhere safe: without it, encrypted pay data cannot be read.
  Never change it after salaries are loaded.

## HR

- Employees: permanent employee IDs (for example 2026-0001), linked to a portal account. Bulk upload from a template.
- Bank details are off by default. The owner can turn them on in Admin. Off means account numbers stay with the bank,
  and payroll uses the payout list (employee ID, name, net pay).
- Schedules: upload one row per person per day, or a weekly pattern with From and To dates.
- Leave: types, yearly balances, requests and approvals. Holiday calendar: regular and special days.

## Attendance

- Correction and overtime requests go to the branch supervisor, HR, a manager or the owner. An approved correction
  changes the attendance record. Approved overtime is paid.
- The Attendance Report works out Present, Late, Undertime, Absent, On leave, Rest day and Holiday from the schedule.

## Payroll

- Basic pay from the rate (monthly or daily) and attendance; overtime, night differential, rest day and holiday premiums;
  allowances (de minimis amounts are tax free up to their ceilings); bonuses from Branch KPI actuals against targets;
  adjustments; SSS, PhilHealth and Pag-IBIG employee shares; withholding tax (2023 onward table).
- Every value is a setting on the Pay Settings page. The payroll lead must confirm them before go-live.
- Not covered yet: minimum wage earner exemption, the 90,000 ceiling on 13th month and other benefits, loans,
  year-end annualization. Use adjustments for these until they are added.

## CRM

- Clients with a status; a call-back table (who calls which client, when); bulk upload; random, even assignment of
  untouched clients; notifications on the Home page.
- Link to Branch KPI (owner, on the CRM Report page): count contacts or closed sales per branch per day for one metric,
  then either check what branches typed, or fill the entries. Branch achievement compares the count with the target.

## Checks

`python test_logic.py`, `python test_att.py`, `python test_hr.py`, `python test_payroll.py`, `python test_crm.py`.

---

# Company Portal: Attendance and Branch KPI in one app

One app, one database, one account per person.

- The main page is open to anyone and has two links: Attendance and Branch KPI. It has no sign-in form.
- Either link leads to the sign-in page. After one sign-in the person can move between the sections they are allowed to open.
- The owner manages every account on one Users page.

## Roles

| Role | Attendance | Branch KPI |
|---|---|---|
| employee | Own time in and time out | No access |
| branch | Own time in and time out | Daily Entry, My Branch, My Cluster |
| manager | Own, plus Attendance Today and Attendance Report | Dashboards and Quarter Ranking |
| owner | All of the above, plus Corrections | Everything, plus Admin and Users |

## Attendance rules

- Time In opens a record. Time Out closes it. A person can do this more than once a day, and the hours are added up.
- Times are stored in UTC and shown in one time zone. Set it with the `APP_TIMEZONE` secret (default `Asia/Manila`).
- A record still open after 16 hours is flagged "No time out". The person can time in again. Only the owner can correct the old record.
- Corrections and added records need a reason and are written to the activity log.
- The app records the time of the click. It does not check where the person is or which device they use.

## Adding the 65 users

Users page, "Add many users from a file". Upload a .csv with the columns Username, Full Name, Role, Branch.
The page shows each new user's temporary password once and lets you download the list. Each user must set their
own password at first sign-in. Delete the downloaded file after handing the passwords out.

## Clusters and the quarter ranking

- Each branch belongs to a cluster. Branch01 to Branch05 are Cluster01, Branch06 to Branch10 are Cluster02, and so on.
  The owner can move a branch on the Admin page.
- Quarter Ranking (manager, owner): quarter to date for all branches and for each cluster, with the previous quarter.
- My Cluster (branch): the figures of the branches in the person's own cluster only. Program Rank is counted across
  all branches, and Cluster Rank is the position inside the cluster.

## Updating a database that already runs the Branch KPI app

Upload the new files. On the next start the app adds the cluster column, the attendance table and the employee role.
Existing users, entries and passwords are kept. Export a copy of the data first.

Optional secrets: `APP_TIMEZONE = "Asia/Manila"` and `PORTAL_NAME = "Company Portal"`.
Files to upload: `app.py`, `kpi_logic.py`, `att_logic.py`, `requirements.txt`, `README.md`, the `data` folder, `.streamlit/config.toml`.

## Checks

`python test_logic.py` (Branch KPI) and `python test_att.py` (accounts and attendance).

---

The sections below are from the Branch KPI app and still apply.

## Deploy with a hosted PostgreSQL database

1. Create the database.
   - Sign up at neon.com (or supabase.com) and create a project.
   - Copy the connection string. It starts with `postgresql://` and should end with `?sslmode=require`.
2. Put the files in a private GitHub repository: `app.py`, `kpi_logic.py`, `requirements.txt`, `README.md`,
   the `data` folder, and `.streamlit/config.toml`. Do not upload any file that holds the real connection string.
3. On share.streamlit.io, create the app from that repository with `app.py` as the main file.
4. Before or after the first deploy, open the app's Settings, then Secrets, and paste these three lines with your own values:

   ```
   DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
   ADMIN_USERNAME = "owner"
   ADMIN_PASSWORD = "choose-a-strong-password-1"
   ```

5. Save. The app restarts. On the first start it creates the tables, loads the metrics, the branches and
   the 15 sample branch files, and creates the owner account. This first start can take about a minute.
6. Sign in as the owner. Open Users and add one account per person.
7. In the Share menu, make the app public so people can open the link without a Streamlit account.
   They still need their own username and password to get past the sign-in page.

To start with no sample entries, add `LOAD_SAMPLE_DATA = "false"` to the secrets before the first start.

## Staying signed in after a refresh

Streamlit forgets who is signed in when the page is refreshed. To keep the user signed in, the app adds a
random code to the page address after sign-in (it looks like `?s=...`). On a refresh the app reads the code
and restores the user.

- The code works for 12 hours. Change `SESSION_HOURS` in `kpi_logic.py` to set another limit.
- Sign out ends it at once. A password reset or deactivating the user also ends it.
- Only a hash of the code is stored in the database.
- Anyone who has the full address with the code is signed in as that user until it expires.
  Users should copy only the plain app address when sharing a link, and sign out on shared devices.

## Going live with real data

1. Admin page, Metrics and multipliers: set up the real metric list.
   - Add each real metric with its multiplier.
   - Deactivate the sample metrics that are not used (Cat_001 and so on). Branches are asked for the active ones only.
   - The list can be any length, for example 15. Submission Check counts the active metrics.
2. Admin page, Remove sample data: tick the box and click Remove sample entries. This deletes only the sample
   rows loaded at first start. Entries typed or imported by users are kept.
3. Admin page, Import a branch file: import each branch's July to September file.
4. Branches then enter each day on the Daily Entry page.
5. Older history can be imported later, one branch file at a time. Importing never creates duplicates.
   Past rankings change once older data is added, because the app always calculates from what is stored.

A month with nothing before it shows no comparison with the previous month. That is expected for the first month loaded.

## Password lockout

After 5 wrong passwords in a row within 15 minutes, the account is locked for 15 minutes.
The owner can unlock it at once with Reset password on the Users page. Each lock is written to the activity log.
Change `MAX_FAILED_LOGINS` and `LOCK_MINUTES` in `kpi_logic.py` to set other limits.

## Faster loading

The app keeps the entries in memory for up to 2 minutes, so a click does not reload everything from the database.
The memory is cleared straight after a save, an import, a multiplier change or a new branch, so those show at once.
Changes made by another user show within 2 minutes.

## Adding a branch

Example: a new branch, Branch21, for the Philippines.

1. Admin page, Branches: enter the code `Branch21` and the name `Philippines`, then click Add branch.
   These are the same two fields as Dim_Branch in the Excel model (Branch Code and Branch Name).
2. Users page: create the user for the branch, for example `branch21`, with the role branch and the branch Branch21.
3. Admin page, Import a branch file: upload its history file if it has one. Otherwise the user starts entering today.

From that point Submission Check expects 21 branches, and the branch is ranked as soon as it has entries.
A branch with no entries shows as No data and has no rank.

## Importing branch files

The owner can load a whole branch file on the Admin page, under Import a branch file.

1. Choose the branch.
2. Upload the file: `.xlsx` with a sheet named `data`, or `.csv`. Columns: Date, Metric, Metric Value.
3. Read the summary and any warnings, then click Import.

Rows for a date and metric that already exist are replaced, so importing the same file twice does not create
duplicates. Blank values are skipped. Rows with an unknown metric, an unreadable date, or a value that is not
a whole number of 0 or higher are skipped and reported.

## Updating an app that is already deployed

Replace `app.py`, `kpi_logic.py`, `requirements.txt`, `test_logic.py` and `README.md` in the GitHub repository.
The app updates the database by itself on the next start (new tables and columns are added, nothing is removed).
The app restarts and adds the new `sessions` table by itself. Existing entries and users are kept.

## Roles

| Role | Sees |
|---|---|
| branch | Daily Entry and My Branch for the own branch only, My Account |
| manager | Main Dashboard, KPI Dashboard, Drill-down, My Account |
| owner | All pages, plus Submission Check, Data Quality, Users and Admin |

## Try it on a PC without PostgreSQL

1. `pip install -r requirements.txt`
2. `streamlit run app.py`
3. The first screen asks you to create the owner account. Data is kept in `kpi.db` in this folder.

## Files

- `app.py`: the pages (Streamlit).
- `kpi_logic.py`: database, accounts and calculations. No page code.
- `test_logic.py`: 80 checks. Run `python test_logic.py`. Set `DATABASE_URL` to an empty test database to run them on PostgreSQL.
- `data/`: metrics, branches and sample entries loaded on the first start.
- `.streamlit/secrets.toml.example`: the three settings to paste into Secrets.

## What was tested

- All 80 checks pass on SQLite and on a real PostgreSQL 16 server. They cover the Excel numbers
  (total 158,954.7, Australia rank 1, Russia rank 15, September 18,383.3, change +17.15%), entry rules,
  the account rules (temporary password, forced change, reset, deactivate, hashing, activity log),
  and the stay-signed-in rules (refresh, sign-out, expiry, reset and deactivate end the session).
- Every page was run for every role with a stand-in for Streamlit, on both databases, with no code errors.
- Not tested in the build environment: the app in a real browser, and the real PostgreSQL driver (psycopg2).
  Neither could be installed there. The PostgreSQL checks sent the same SQL to the server through the psql tool.
  Click through each page once after deploying.

## Still needed before real production use

1. Daily database backups (paid database plans include them).
2. A server that does not sleep, and a web address of the company's own.
3. Someone who can maintain the code and the database.
