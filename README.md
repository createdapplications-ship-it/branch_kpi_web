# Branch KPI web app (PostgreSQL version with real user accounts)

Branches type the daily values into a web form. The values go into a PostgreSQL database.
The dashboard pages read that database. Entries stay saved when the app restarts.

Rule: Adjusted Value = Metric Value x multiplier. Branches are ranked by total Adjusted Value.

## What changed from the first prototype

- Database: PostgreSQL when `DATABASE_URL` is set. Without it, the app uses a local SQLite file so it can still be tried on a PC.
- Accounts: no demo logins. The owner creates one account per person on the Users page.
  Each new user gets a temporary password and must set their own at first sign-in.
- Passwords are stored hashed with a separate salt per user. Nobody can read them, including the owner.
- The owner can reset a password and deactivate or reactivate a user.
- Every sign-in, failed sign-in, save and user change is written to the activity log.
- A page refresh keeps the user signed in. The sign-in lasts 12 hours or until Sign out. See the section below.

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
- `test_logic.py`: 60 checks. Run `python test_logic.py`. Set `DATABASE_URL` to an empty test database to run them on PostgreSQL.
- `data/`: metrics, branches and sample entries loaded on the first start.
- `.streamlit/secrets.toml.example`: the three settings to paste into Secrets.

## What was tested

- All 60 checks pass on SQLite and on a real PostgreSQL 16 server. They cover the Excel numbers
  (total 158,954.7, Australia rank 1, Russia rank 15, September 18,383.3, change +17.15%), entry rules,
  the account rules (temporary password, forced change, reset, deactivate, hashing, activity log),
  and the stay-signed-in rules (refresh, sign-out, expiry, reset and deactivate end the session).
- Every page was run for every role with a stand-in for Streamlit, on both databases, with no code errors.
- Not tested in the build environment: the app in a real browser, and the real PostgreSQL driver (psycopg2).
  Neither could be installed there. The PostgreSQL checks sent the same SQL to the server through the psql tool.
  Click through each page once after deploying.

## Still needed before real production use

1. A lockout after repeated wrong passwords.
2. Daily database backups (paid database plans include them).
3. A server that does not sleep, and a web address of the company's own.
4. Someone who can maintain the code and the database.
