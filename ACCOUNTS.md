# Employee ID authentication — setup and operation

Everything about who can sign in to Fleet Fuel Optimization: the database, the
commands, and the decisions behind them. The short version is at the top; the
reasoning is at the bottom.

---

## Run it, from nothing

From the project root, with the virtual environment active:

```bash
# 1. Dependencies (SQLAlchemy, Alembic, bcrypt, PyJWT are new)
pip install -r backend/requirements.txt

# 2. Configuration
copy .env.example .env                              # Windows
# cp .env.example .env                              # macOS / Linux

#    Generate a signing key and paste it into .env as QGF_JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. Create the database
python -m alembic upgrade head

# 4. Create accounts — pick ONE
python -m backend.manage seed                       # demo staff, for a run-through
python -m backend.manage bootstrap                  # one real admin, prompts for a password

# 5. Start
start.bat                                           # Windows: API + web UI
./start.sh                                          # macOS / Linux
```

Then open <http://localhost:5173> and sign in.

`start.bat` and `./start.sh` now do steps 2–4 themselves on a first run,
including generating the signing key, so in practice the whole thing is just
`start.bat`. The commands above are what it runs, for when you want to do it
by hand or something goes wrong.

### If it says `No module named alembic`

The dependencies are missing from **this project's** virtual environment.
Install them by calling the venv's interpreter directly:

```
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Then run `start.bat` again.

Worth knowing why, because it is a trap that will bite again otherwise: a
virtual environment records its own absolute path in `activate.bat` when it is
created. Copy or rename the project folder — `quantum-green-fleet` →
`Qfleet_Optimization`, say — and `activate.bat` still points at the old
location. Activation then *appears* to succeed, the prompt even shows
`(venv)`, but `python` falls through to the system interpreter, which has its
own unrelated set of packages. You end up looking at `No module named alembic`
from a folder whose venv has alembic sitting in it.

`start.bat` and `start.sh` now handle both halves of this: they call the venv's
interpreter by absolute path rather than trusting activation, and they detect a
relocated venv and rewrite its scripts in place (which keeps every installed
package). To repair one by hand:

```
python -m venv venv          REM over the existing folder; packages survive
```

### Demo credentials (`manage seed`)

| Employee ID | Name | Role | Password |
| --- | --- | --- | --- |
| `EMP001` | Fleet Administrator | ADMIN | `Admin@12345` |
| `EMP002` | Priya Nair | EMPLOYEE | `Fleet@12345` |
| `EMP003` | Arjun Menon | EMPLOYEE | `Fleet@12345` |
| `EMP004` | Sara Iqbal | EMPLOYEE | `Fleet@12345` |
| `EMP005` | Rohit Deshmukh | ADMIN | `Admin@12345` |

These are written into a public repository. They are fine for a demo and for
nothing else. For anything real, use `bootstrap` and delete the seeded rows.

---

## 1. What changed

**New — backend**

| File | What it is |
| --- | --- |
| `backend/db/base.py` | Declarative base, explicit constraint naming |
| `backend/db/models.py` | The `Employee` model and `Role` |
| `backend/db/session.py` | Engine, session factory, the FastAPI dependency |
| `backend/auth/security.py` | bcrypt hashing, JWT issue and verify. No FastAPI, no ORM |
| `backend/auth/schemas.py` | Request/response shapes. Responses list fields by name |
| `backend/auth/service.py` | The account rules — duplicates, last-admin, password set |
| `backend/auth/deps.py` | `get_current_employee`, `require_admin` |
| `backend/auth/api.py` | `/api/auth/*` |
| `backend/admin/api.py` | `/api/admin/*`, ADMIN only |
| `backend/manage.py` | Account administration from the command line |
| `backend/tests/test_auth.py` | 78 tests on the boundary |
| `migrations/` + `alembic.ini` | The `employees` table |
| `.env.example` | Every setting, with placeholders and no secrets |

**Changed — backend**

| File | Change |
| --- | --- |
| `backend/config.py` | `.env` loading; `DATABASE_URL`, JWT and bcrypt settings |
| `backend/core/errors.py` | `AuthenticationError`, `PermissionError_`, `ConflictError` |
| `backend/main.py` | Registers the two routers; `accounts` in `/api/health`; a startup warning when no admin exists |
| `backend/requirements.txt` | sqlalchemy, alembic, bcrypt, PyJWT, python-dotenv |
| `backend/tests/test_api.py` | Health and OpenAPI assertions widened |
| `apitest.py` | An `[Authentication]` section; 74 → 94 checks |
| `start.bat`, `start.sh` | Create `.env`, migrate, seed on a first run |

**Changed — frontend**

| File | Change |
| --- | --- |
| `src/pages/Login.jsx` | Work email → **Employee ID**; real API call; server errors. Nothing else touched |
| `src/lib/auth.js` | Rewritten against the API: token, revalidation, role |
| `src/lib/api.js` | Bearer-token interceptor, 401 handling, `auth` and `admin` methods |
| `src/components/RequireAuth.jsx` | Waits for revalidation; adds `RequireAdmin` |
| `src/components/AppShell.jsx` | Role-gated nav; the account block shows ID and department |
| `src/lib/nav.js` | An `Employees` item, ADMIN only |
| `src/App.jsx` | The `/admin` route; revalidates the stored token on load |
| `src/pages/Admin.jsx` | **New** — the employee management dashboard |

**Untouched:** every optimisation, prediction, benchmarking, scenario and
regulatory module, and all nine existing pages. Verified — see §13.

---

## 2. Which database

**SQLite, via SQLAlchemy**, at `backend/data/qfleet.db`. Switching to
PostgreSQL is one environment variable and no code change:

```bash
pip install "psycopg[binary]"
# in .env:
QGF_DATABASE_URL=postgresql+psycopg://qfleet:your-password@localhost:5432/qfleet
python -m alembic upgrade head
```

The brief suggested PostgreSQL, so this is a deliberate departure and worth
stating plainly rather than burying.

The reason is the demo. This project has to come up from `start.bat` on a
laptop, in a hall, possibly with no network — and the team's own risk list
puts venue setup failure at the top. A default that first needs a database
server installed, running and reachable turns a one-command start into a
support call at the worst possible moment. SQLite needs nothing, survives a
hard power-off (WAL mode), and is a real relational database with the same
SQL, the same migrations and the same ORM code.

Nothing about that choice is load-bearing. The schema and every query are
dialect-neutral, the migration runs on both, and the test suite passes against
either. When this goes anywhere multi-user, change the variable.

There was no existing database in the project — the only "session" state was
the in-memory scenario fleet in `scenario/api.py` — so nothing was duplicated.

---

## 3. The schema

One table.

```sql
CREATE TABLE employees (
    id            INTEGER      NOT NULL PRIMARY KEY AUTOINCREMENT,
    employee_id   VARCHAR(32)  NOT NULL,            -- the login identifier
    full_name     VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,            -- bcrypt; never returned
    role          VARCHAR(16)  NOT NULL DEFAULT 'EMPLOYEE',
    department    VARCHAR(80)  NOT NULL DEFAULT '',
    email         VARCHAR(254),                     -- optional
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_employees_role_valid CHECK (role IN ('ADMIN', 'EMPLOYEE'))
);
CREATE UNIQUE INDEX ix_employees_employee_id ON employees (employee_id);
```

Three details that are not decoration:

- **`employee_id` is stored upper-cased and whitespace-collapsed**
  (`normalise_employee_id`), on write *and* on lookup. Without that, `EMP001`
  and `emp001 ` become two accounts and the unique index is a lie. Signing in
  as `emp001` works.
- **The unique index is the real duplicate check.** The service layer also
  checks first, for a clean error message, but two administrators submitting
  `EMP007` at the same instant are separated by the index, not by the check.
- **`is_active` rather than deletion.** Revoking access without losing who the
  account belonged to is what an operator actually needs; delete is there too,
  but deactivate is the default gesture.

---

## 4. How authentication works

```
Employee ID + password
   │
   ├─ POST /api/auth/login
   │     look up employees.employee_id (normalised)
   │     bcrypt.checkpw(password, password_hash)
   │     reject if is_active is false
   │     └─ sign a JWT: {sub: id, eid, role, iat, exp, iss}
   │
   ├─ the browser stores the token (localStorage if "remember me", else sessionStorage)
   ├─ every request carries  Authorization: Bearer <token>
   │
   └─ get_current_employee: verify signature and expiry → re-read the row →
      reject if the account is gone or inactive
         └─ require_admin: reject unless role == 'ADMIN'
```

**Passwords** are bcrypt, cost 12, salted per hash. There is no code path that
stores, logs, or returns a plain password, and none that returns a hash: every
response is built by `EmployeeOut`, which lists its fields by name, so adding a
column to the model later cannot leak one.

**Sessions** are stateless JWTs, 12 hours by default (`QGF_JWT_EXPIRE_MINUTES`).
Stateless means signing out is a client-side discard — `POST /api/auth/logout`
confirms and logs it but revokes nothing, and the code says so rather than
implying otherwise.

**The one thing stateless tokens cannot normally do**, they do here:
`get_current_employee` re-reads the employee row on every request instead of
trusting the token's claims. That is one indexed lookup, and it means
deactivating someone in the dashboard ends their session *now* rather than
whenever their token happens to expire. The frontend also revalidates a stored
token against `/api/auth/me` before rendering anything behind the gate.

### Not revealing whether an Employee ID exists

An unknown ID and a wrong password produce **the same status, the same error
code and the same message**: `Invalid Employee ID or password`. Three further
steps, because the message alone is not enough:

- **Timing.** An unknown ID would otherwise return in microseconds while a
  wrong password takes ~250 ms of bcrypt — a perfectly good oracle whatever the
  text says. `dummy_verify()` hashes against a real throwaway digest so both
  paths cost the same.
- **No shape validation on the login path.** The admin form rejects a malformed
  Employee ID; the login form does not. "That is not a valid Employee ID" tells
  an attacker which patterns are worth trying.
- **Nothing in the response names the employee.** Asserted by test.

The deliberate exception is a *disabled* account, which says so. That does
disclose the ID exists — and it is the right trade: someone whose account was
revoked needs to know to call an administrator rather than retrying their
password. Set `QGF_DISCLOSE_INACTIVE=false` to fold it into the generic
message.

---

## 5. Creating the first administrator

Nobody is signed in yet, so this one is the command line:

```bash
python -m backend.manage bootstrap
```

It prompts for the password twice and never echoes it. Defaults to `EMP001` /
"Fleet Administrator" / "Operations"; override with `--employee-id`, `--name`,
`--department`, `--email`. It refuses if an active administrator already
exists, unless you pass `--force`.

For unattended setup, put `QGF_ADMIN_EMPLOYEE_ID`, `QGF_ADMIN_NAME` and
`QGF_ADMIN_PASSWORD` in `.env` and run it with no arguments — then take the
password back out of `.env`.

---

## 6. Adding an employee

**The normal way — the dashboard.** Sign in as an administrator, open
**Employees** in the sidebar, press **Add employee**. Employee ID, full name,
department, role, optional email, password and confirmation, active or not.
Everything is validated, and a duplicate Employee ID is refused in any casing.

**From the command line:**

```bash
python -m backend.manage add EMP010 "Anita Rao" --department Bunkering
python -m backend.manage add EMP011 "Vikram Shah" --role ADMIN --email vikram@operator.com
```

The password is prompted for. `--password` exists for scripts and is
documented as the thing that puts a password in your shell history.

---

## 7. Deactivating an employee

Dashboard: the **person-with-a-cross** icon on their row. Or:

```bash
python -m backend.manage deactivate EMP010
python -m backend.manage activate EMP010          # back again
```

They cannot sign in, and any session they already have stops working on their
next request. The record, and everything it tells you about who they were,
stays.

Three things are refused, by the API and not merely by a greyed-out button:
deactivating yourself, demoting yourself, and demoting or deactivating the last
active administrator. Any of them would lock everyone out of employee
management with no way back short of the command line.

---

## 8. Resetting a password

Nobody can read a password back — not the API, not the dashboard, not the
database. A reset is the only recovery.

Dashboard: the **key** icon on their row, then the new password twice. Or:

```bash
python -m backend.manage passwd EMP010
```

An employee can change their own without an administrator:
`POST /api/auth/change-password` with their current and new password. (The
frontend does not surface this yet — it is an API call today.)

---

## 9. Running migrations

```bash
python -m alembic upgrade head        # apply everything outstanding
python -m alembic current             # what is applied
python -m alembic history             # what exists
python -m alembic downgrade -1        # step back one
```

Run from the **project root**, where `alembic.ini` is. The database URL is not
in `alembic.ini` — `migrations/env.py` reads it from the application settings,
so a connection string with a password never lands in a committed file, and
migrations always run against exactly the database the API will use.

`python -m backend.manage init` creates the tables directly for a throwaway
database. It is a convenience; `alembic upgrade head` is the real path, because
it is the one that can also upgrade an existing database.

---

## 10. Starting the application

```bash
start.bat                             # Windows — API + web UI
./start.sh                            # macOS / Linux
./start.sh --api-only                 # no UI
```

Or by hand, in two terminals:

```bash
cd backend && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
cd frontend && npm run dev
```

- Web UI — <http://localhost:5173>
- API — <http://localhost:8000>, docs at `/docs`
- Health — <http://localhost:8000/api/health>, which now reports `accounts`

Both bind to `127.0.0.1`. Nothing on the venue Wi-Fi can reach them.

---

## 11. Environment variables

All in `.env.example`, with placeholders and no real values. `.env` is
git-ignored; the environment always wins over the file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `QGF_DATABASE_URL` | `sqlite:///backend/data/qfleet.db` | Any SQLAlchemy URL |
| `QGF_JWT_SECRET` | *(random per process)* | **Set this.** Unset, every restart signs everyone out |
| `QGF_JWT_ALGORITHM` | `HS256` | |
| `QGF_JWT_EXPIRE_MINUTES` | `720` | Session length — 12 hours |
| `QGF_BCRYPT_ROUNDS` | `12` | Hashing cost |
| `QGF_PASSWORD_MIN_LENGTH` | `8` | |
| `QGF_DISCLOSE_INACTIVE` | `true` | Whether a disabled account is told it is disabled |
| `QGF_DB_ECHO` | `false` | Log every SQL statement |

Generate a key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**No database credential or signing key reaches the browser.** The frontend
knows one URL prefix (`/api`) and one bearer token it was handed at sign-in.
There is no connection string, no credential and no direct database access in
any client-side file — and, because the schema is behind an API rather than
exposed as a query endpoint, no way for a signed-in employee to reach the
database at all except through the routes above.

---

## 12. The admin dashboard

**Employees** in the sidebar, or <http://localhost:5173/admin>. Administrators
only.

- Add, with full validation and no duplicate IDs
- Search across Employee ID, name, department and email; filter by role and
  status
- Edit name, department, role, email, active status. The Employee ID is fixed —
  it is the login identifier, and silently changing it would orphan someone
- Reset a password
- Activate / deactivate
- Delete
- Counts across the top: accounts, active, administrators

The link is hidden from ordinary employees and `/admin` redirects them away.
**Neither of those is the permission.** `require_admin` is declared on the
admin *router*, so every route under it — including any added later — refuses a
non-administrator with 403 regardless of what the browser does. There is a test
that fails if that dependency is ever moved onto individual routes, and another
that fails if a new admin route is added without an authorization test.

---

## 13. What was verified

| Check | Result |
| --- | --- |
| `python -m pytest backend/tests -q` | **268 passed** (78 new) |
| `python apitest.py` against a live server | **94/94** (20 new) |
| `npm run build` | clean |
| `npm run lint` | clean (only pre-existing fast-refresh warnings) |
| End-to-end in a real browser | below |

The browser pass, at 1560 px and 400 px, in both themes:

- the login page renders with **EMPLOYEE ID** / `EMP001`, and the chart panel,
  branding, tagline, statistics, remember-me, show/hide and forgot-password are
  all still there;
- a wrong password and an unknown Employee ID produce byte-identical messages;
- `emp001` in lower case signs in;
- an employee sees no Employees link, is redirected away from `/admin`, **and
  gets 403 when calling `/api/admin/employees` directly with their own token**;
- all nine existing pages load, with no console errors and no horizontal
  overflow;
- an administrator adds EMP777 through the UI, searches for them, resets their
  password — the old password stops working, the new one works;
- deactivating EMP777 from another session drops them to `/login` on their next
  page view;
- a token issued before an API restart still works afterwards, because the
  signing key is in `.env` rather than generated per process.

---

## A scope decision worth knowing about

`/api/auth/*` and `/api/admin/*` require a token. **The optimisation,
prediction, benchmarking, scenario and regulatory routes are still open**, as
they were before any of this existed.

That is a line drawn on purpose. The requirement was about employee accounts
and the admin surface, and those are locked. Locking the rest would mean
reworking `/api/optimization/stream`: the sandbox consumes it with
`EventSource`, which cannot send an `Authorization` header, so the token would
have to move into a cookie or a query string — a query string being the version
that puts credentials in server logs. Those endpoints expose computation over
bundled public data and no personal information, and the server listens on
localhost only.

If you want them closed, it is two changes: add
`dependencies=[Depends(get_current_employee)]` to each router in
`backend/main.py`, and give the SSE stream a cookie-based session. The 74
existing conformance checks in `apitest.py` would need tokens too.
