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
- `test_logic.py`: 37 checks. Run `python test_logic.py`. Set `DATABASE_URL` to an empty test database to run them on PostgreSQL.
- `data/`: metrics, branches and sample entries loaded on the first start.
- `.streamlit/secrets.toml.example`: the three settings to paste into Secrets.

## What was tested

- All 37 checks pass on SQLite and on a real PostgreSQL 16 server. They cover the Excel numbers
  (total 158,954.7, Australia rank 1, Russia rank 15, September 18,383.3, change +17.15%), entry rules,
  and the account rules (temporary password, forced change, reset, deactivate, hashing, activity log).
- Every page was run for every role with a stand-in for Streamlit, on both databases, with no code errors.
- Not tested in the build environment: the app in a real browser, and the real PostgreSQL driver (psycopg2).
  Neither could be installed there. The PostgreSQL checks sent the same SQL to the server through the psql tool.
  Click through each page once after deploying.

## Still needed before real production use

1. A lockout after repeated wrong passwords, and a session timeout.
2. Daily database backups (paid database plans include them).
3. A server that does not sleep, and a web address of the company's own.
4. Someone who can maintain the code and the database.
